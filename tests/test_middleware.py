"""Tests for middleware components using TestClient."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.middleware import register_middleware
from app.utils.logger import get_request_id


@pytest.fixture
def app():
    """Create a minimal FastAPI app for middleware testing."""
    app = FastAPI()

    @app.get("/test")
    async def test_endpoint():
        return {"message": "ok", "request_id": get_request_id()}

    @app.get("/error")
    async def error_endpoint():
        raise ValueError("Test error")

    register_middleware(app)
    return app


@pytest.fixture
def client(app):
    """Create a TestClient for the test app."""
    return TestClient(app)


def test_health_check_route(client):
    """A simple route should return normally."""
    response = client.get("/test")
    assert response.status_code == 200
    assert response.json()["message"] == "ok"


def test_cors_headers_present(client):
    """CORS headers should be present in responses."""
    response = client.get("/test", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_allows_localhost_5173(client):
    """CORS should allow the frontend dev server origin."""
    response = client.options(
        "/test",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_localhost_8000(client):
    """CORS should allow the backend port as well."""
    response = client.options(
        "/test",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8000"


def test_not_found_returns_json(client):
    """A 404 should still return JSON."""
    response = client.get("/nonexistent-route")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_cors_allows_credentials(client):
    """CORS should allow credentials."""
    response = client.options(
        "/test",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_allows_all_methods(client):
    """CORS should allow all methods (wildcard)."""
    response = client.options(
        "/test",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    allow_methods = response.headers.get("access-control-allow-methods", "")
    assert "*" in allow_methods or "POST" in allow_methods


def test_request_id_in_response_header(client):
    """Every response should include X-Request-ID header."""
    response = client.get("/test")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


def test_request_id_propagated_to_handler(client):
    """request_id set by middleware should be accessible inside handler."""
    response = client.get("/test", headers={"X-Request-ID": "my-custom-id"})
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == "my-custom-id"
