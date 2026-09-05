"""End-to-end integration tests using httpx.AsyncClient.

Tests the full API lifecycle including auth, research, settings,
knowledge base, and health check endpoints.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.fixture
async def client(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealth:
    """Health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_health_has_request_id(self, client):
        resp = await client.get("/health")
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) > 0


class TestAuth:
    """Registration, login, token refresh, and protected endpoints."""

    @pytest.mark.asyncio
    async def test_register_and_login(self, client):
        # Register
        reg = await client.post("/api/auth/register", json={
            "username": "testuser",
            "password": "testpass123",
        })
        assert reg.status_code == 200
        assert reg.json()["username"] == "testuser"

        # Login
        login = await client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "testpass123",
        })
        assert login.status_code == 200
        tokens = login.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_register_duplicate(self, client):
        reg = await client.post("/api/auth/register", json={
            "username": "dupeuser",
            "password": "pass123",
        })
        assert reg.status_code == 200

        dup = await client.post("/api/auth/register", json={
            "username": "dupeuser",
            "password": "otherpass",
        })
        assert dup.status_code == 409

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        await client.post("/api/auth/register", json={
            "username": "wrongpwd",
            "password": "correctpass",
        })
        login = await client.post("/api/auth/login", json={
            "username": "wrongpwd",
            "password": "wrongpass",
        })
        assert login.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token(self, client):
        await client.post("/api/auth/register", json={
            "username": "refreshtest",
            "password": "pass123",
        })
        login = await client.post("/api/auth/login", json={
            "username": "refreshtest",
            "password": "pass123",
        })
        tokens = login.json()

        refresh = await client.post("/api/auth/refresh", json={
            "refresh_token": tokens["refresh_token"],
        })
        assert refresh.status_code == 200
        new_tokens = refresh.json()
        assert "access_token" in new_tokens

    @pytest.mark.asyncio
    async def test_me_endpoint(self, client):
        await client.post("/api/auth/register", json={
            "username": "metest",
            "password": "pass123",
        })
        login = await client.post("/api/auth/login", json={
            "username": "metest",
            "password": "pass123",
        })
        token = login.json()["access_token"]

        me = await client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert me.status_code == 200
        assert me.json()["username"] == "metest"

    @pytest.mark.asyncio
    async def test_me_unauthorized(self, client):
        me = await client.get("/api/auth/me")
        assert me.status_code == 401


class TestResearch:
    """Research task lifecycle via API."""

    @pytest.mark.asyncio
    async def test_start_research(self, client):
        resp = await client.post("/api/research", json={
            "task": "test research task",
            "max_iterations": 1,
            "format": "markdown",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_task_status(self, client):
        start = await client.post("/api/research", json={
            "task": "status test",
            "max_iterations": 1,
        })
        task_id = start.json()["task_id"]

        status = await client.get(f"/api/research/{task_id}")
        assert status.status_code == 200
        data = status.json()
        assert data["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_nonexistent_task(self, client):
        resp = await client.get("/api/research/nonexistent-task-id")
        assert resp.status_code == 404


class TestSettings:
    """Settings API (non-destructive tests only)."""

    @pytest.mark.asyncio
    async def test_get_settings(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        # Should have either configured=True or configured=False
        assert "configured" in data

    @pytest.mark.asyncio
    async def test_post_settings_empty_key(self, client):
        resp = await client.post("/api/settings", json={
            "provider": "openai",
            "api_key": "",
            "model": "gpt-4o",
        })
        assert resp.status_code == 422


class TestKnowledge:
    """Knowledge base API."""

    @pytest.mark.asyncio
    async def test_ingest_document(self, client):
        resp = await client.post("/api/knowledge/ingest", json={
            "content": "Test document content about AI agents.",
            "source": "test_integration",
            "doc_type": "text",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_ingest_empty_content(self, client):
        resp = await client.post("/api/knowledge/ingest", json={
            "content": "",
            "source": "test",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_knowledge_search(self, client):
        resp = await client.get("/api/knowledge/search?q=AI+agents&k=3")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))


class TestCORS:
    """CORS headers."""

    @pytest.mark.asyncio
    async def test_cors_header_present(self, client):
        resp = await client.get("/health", headers={
            "Origin": "http://localhost:5173",
        })
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
