"""Runtime LLM settings persistence — reads/writes config JSON in the data volume."""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


class RuntimeLLMConfig:
    """Holds one LLM configuration set."""

    def __init__(
        self,
        provider: str = "openai",
        api_key: str = "",
        model: str = "gpt-4o",
        base_url: str = "",
        embedding_model: str = "text-embedding-v3",
        embedding_api_key: str = "",
        embedding_base_url: str = "",
        reranker_enabled: bool = False,
        reranker_api_key: str = "",
        reranker_base_url: str = "",
        reranker_model: str = "",
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or DEFAULT_BASE_URLS.get(provider, "")
        self.embedding_model = embedding_model
        self.embedding_api_key = embedding_api_key
        self.embedding_base_url = embedding_base_url
        self.reranker_enabled = reranker_enabled
        self.reranker_api_key = reranker_api_key
        self.reranker_base_url = reranker_base_url
        self.reranker_model = reranker_model

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "model": self.model,
            "base_url": self.base_url,
            "embedding_model": self.embedding_model,
            "embedding_api_key": self.embedding_api_key,
            "embedding_base_url": self.embedding_base_url,
            "reranker_enabled": self.reranker_enabled,
            "reranker_api_key": self.reranker_api_key,
            "reranker_base_url": self.reranker_base_url,
            "reranker_model": self.reranker_model,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuntimeLLMConfig":
        return cls(
            provider=d.get("provider", "openai"),
            api_key=d.get("api_key", ""),
            model=d.get("model", "gpt-4o"),
            base_url=d.get("base_url", ""),
            embedding_model=d.get("embedding_model", "text-embedding-v3"),
            embedding_api_key=d.get("embedding_api_key", ""),
            embedding_base_url=d.get("embedding_base_url", ""),
            reranker_enabled=bool(d.get("reranker_enabled", False)),
            reranker_api_key=d.get("reranker_api_key", ""),
            reranker_base_url=d.get("reranker_base_url", ""),
            reranker_model=d.get("reranker_model", ""),
        )


def _config_path() -> Path:
    """Return the path to the runtime config JSON file."""
    chroma = os.environ.get("CHROMA_DB_PATH", "./data/chroma_db")
    base = Path(chroma).parent
    config_dir = base / "config"
    return config_dir / "llm_settings.json"


def load_runtime_config() -> Optional[RuntimeLLMConfig]:
    """Load persisted runtime config, return None if not found."""
    path = _config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RuntimeLLMConfig.from_dict(data)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load runtime config: %s", exc)
        return None


def save_runtime_config(config: RuntimeLLMConfig) -> None:
    """Persist runtime config to JSON file."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Runtime config saved to %s", path)


def mask_api_key(api_key: str) -> str:
    """Mask API key for display: show first 4 + last 4 chars."""
    if len(api_key) <= 8:
        return api_key[:4] + "..." if len(api_key) > 4 else api_key
    return api_key[:4] + "..." + api_key[-4:]


def get_active_config() -> RuntimeLLMConfig:
    """Get the effective LLM config: runtime JSON > env vars > defaults."""
    runtime = load_runtime_config()
    if runtime and runtime.api_key:
        return runtime

    # Lazy import to avoid circular deps at module level
    from app.config import settings

    if settings.OPENAI_API_KEY:
        return RuntimeLLMConfig(
            provider="openai",
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL_PLANNER,
            base_url=settings.OPENAI_BASE_URL or "",
        )
    if settings.ANTHROPIC_API_KEY:
        return RuntimeLLMConfig(
            provider="anthropic",
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL_PLANNER,
        )
    logger.warning("No LLM API key found in runtime config or environment variables")
    return RuntimeLLMConfig(api_key="")
