import asyncio
from unittest.mock import MagicMock

import httpx
import psycopg

from cortexstone.api.main import app
from cortexstone.api.v1 import router as health_routes


# Testing if the FastAPI connection is live and healthy.
def get(path: str) -> httpx.Response:
    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            # ASGITransport sends the request directly into the application in memory.
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(send_request())


# This proves:
# - The API process can report that it is alive without PostgreSQL.
# - The response has the expected JSON.
# - The request-ID middleware ran.
# Why it matters: a database failure should not make the process appear dead.
def test_liveness_does_not_require_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


# The versioned endpoint proves that the v1 router is mounted correctly.
def test_versioned_health_endpoint():
    response = get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}


# Check database readiness behavior without using a real database.
def test_readiness_succeeds_when_database_query_succeeds(monkeypatch):
    connection = MagicMock()
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setattr(health_routes.psycopg, "connect", MagicMock(return_value=connection))

    response = get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    connection.__enter__.return_value.execute.assert_called_once_with("SELECT 1")


def test_readiness_fails_when_database_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "service_unavailable",
        "message": "The request could not be completed.",
    }
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_readiness_fails_when_database_connection_fails(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setattr(
        health_routes.psycopg,
        "connect",
        MagicMock(side_effect=psycopg.OperationalError("connection refused")),
    )

    response = get("/health/ready")

    assert response.status_code == 503
    assert "connection refused" not in response.text


# Request a nonexistent route to exercise the shared HTTP error handler.
def test_http_errors_use_the_shared_error_envelope():
    response = get("/not-a-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_successful_health_requests_receive_unique_request_ids():
    first = get("/health/live")
    second = get("/health/live")

    assert first.headers["x-request-id"]
    assert second.headers["x-request-id"]
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_versioned_health_response_has_request_id():
    response = get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_readiness_uses_configured_database_url_and_timeout(monkeypatch):
    database_url = "postgresql://test:test@database.example/test"
    connection = MagicMock()
    connect = MagicMock(return_value=connection)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(health_routes.psycopg, "connect", connect)

    response = get("/health/ready")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    connect.assert_called_once_with(database_url, connect_timeout=2)
    connection.__enter__.return_value.execute.assert_called_once_with("SELECT 1")
