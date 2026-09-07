"""Tests for settings API and config service."""

import os
import tempfile
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.config_service import (
    RuntimeLLMConfig,
    get_active_config,
    load_runtime_config,
    mask_api_key,
    save_runtime_config,
)


@pytest.fixture
def temp_config():
    """Create a temporary config directory and set CHROMA_DB_PATH."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chroma_path = os.path.join(tmpdir, "chroma_db")
        os.environ["CHROMA_DB_PATH"] = chroma_path
        yield
        os.environ.pop("CHROMA_DB_PATH", None)


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Clear the module-level config cache in main.py before each API test."""
    from app.main import _invalidate_config_cache

    _invalidate_config_cache()


@pytest.fixture
def no_env_keys():
    """Patch app.config.settings to have no API keys (avoids .env file pollution)."""
    with patch("app.config.settings.OPENAI_API_KEY", None), patch(
        "app.config.settings.ANTHROPIC_API_KEY", None
    ):
        yield


class TestMaskApiKey:
    def test_masks_long_key(self):
        assert mask_api_key("sk-abcdefghijklmnop") == "sk-a...mnop"

    def test_masks_medium_key(self):
        assert mask_api_key("sk-test123456") == "sk-t...3456"

    def test_short_key_returns_as_is(self):
        assert mask_api_key("abc") == "abc"

    def test_four_char_key(self):
        assert mask_api_key("abcd") == "abcd"

    def test_empty_key(self):
        assert mask_api_key("") == ""


class TestConfigPersistence:
    def test_save_and_load_roundtrip(self, temp_config):
        cfg = RuntimeLLMConfig(
            provider="openai",
            api_key="sk-test-key-123",
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )
        save_runtime_config(cfg)
        loaded = load_runtime_config()
        assert loaded is not None
        assert loaded.provider == "openai"
        assert loaded.api_key == "sk-test-key-123"
        assert loaded.model == "gpt-4o"
        assert loaded.base_url == "https://api.openai.com/v1"

    def test_load_nonexistent_returns_none(self, temp_config):
        loaded = load_runtime_config()
        assert loaded is None

    def test_provider_default_base_url(self):
        cfg = RuntimeLLMConfig(provider="openai", api_key="sk-test")
        assert cfg.base_url == "https://api.openai.com/v1"

        cfg2 = RuntimeLLMConfig(provider="anthropic", api_key="sk-test")
        assert cfg2.base_url == "https://api.anthropic.com"

    def test_custom_base_url_not_overridden(self):
        cfg = RuntimeLLMConfig(
            provider="openai",
            api_key="sk-test",
            base_url="https://custom.api.com/v1",
        )
        assert cfg.base_url == "https://custom.api.com/v1"


class TestGetActiveConfig:
    def test_runtime_config_takes_priority(self, temp_config):
        save_runtime_config(
            RuntimeLLMConfig(
                provider="openai",
                api_key="sk-runtime-key",
                model="gpt-4o",
            )
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-key"}, clear=False):
            result = get_active_config()
            assert result.api_key == "sk-runtime-key"

    def test_falls_back_to_env_var(self, temp_config):
        """Fallback reads from app.config.settings which loads .env file."""
        with patch("app.config.settings.OPENAI_API_KEY", "sk-env-fallback"):
            result = get_active_config()
            assert result.api_key == "sk-env-fallback"

    def test_returns_empty_when_no_key(self, temp_config):
        """When no key is available anywhere, returns empty config."""
        with patch("app.config.settings.OPENAI_API_KEY", None), patch(
            "app.config.settings.ANTHROPIC_API_KEY", None
        ):
            result = get_active_config()
            assert result.api_key == ""
            assert result.provider == "openai"


class TestSettingsAPI:
    @pytest.mark.asyncio
    async def test_get_settings_not_configured(self, temp_config, no_env_keys):
        """With no config saved and no env keys, returns configured=False."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings")
            assert response.status_code == 200
            data = response.json()
            assert data["configured"] is False

    @pytest.mark.asyncio
    async def test_get_settings_configured(self, temp_config):
        """Save a runtime config and verify API returns masked key."""
        save_runtime_config(
            RuntimeLLMConfig(
                provider="openai",
                api_key="sk-test-abc-12345",
                model="gpt-4o",
                base_url="https://api.openai.com/v1",
            )
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings")
            assert response.status_code == 200
            data = response.json()
            assert data["configured"] is True
            assert data["provider"] == "openai"
            # Model comes from the saved config (RuntimeLLMConfig default)
            assert data["model"] == "gpt-4o"
            # API key should be masked
            assert "..." in data["api_key"]
            assert data["api_key"].startswith("sk-t")

    @pytest.mark.asyncio
    async def test_post_settings_empty_key(self, temp_config, no_env_keys):
        """Empty API key should be rejected by Pydantic validation (422)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "provider": "openai",
                    "api_key": "",
                    "model": "gpt-4o",
                },
            )
            # Pydantic Field(..., min_length=1) rejects empty key before handler runs
            assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_settings_connection_fails(self, temp_config):
        """With no real API, connection test should fail and config should not be saved."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "provider": "openai",
                    "api_key": "sk-invalid-test-key",
                    "model": "gpt-4o",
                    "base_url": "https://api.openai.com/v1",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            # Should return a meaningful error message (not raw exception)
            assert isinstance(data["message"], str) and len(data["message"]) > 0

            # Config should NOT be saved
            loaded = load_runtime_config()
            assert loaded is None
