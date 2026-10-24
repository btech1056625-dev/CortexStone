import asyncio

import httpx
from sqlalchemy.exc import SQLAlchemyError

from cortexstone.api.config import Settings
from cortexstone.api.main import app, create_app


def get(path: str, application=app) -> httpx.Response:
    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(send_request())


class FakeConnection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.statement = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def execute(self, statement):
        self.statement = statement
        if self.error is not None:
            raise self.error


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> FakeConnection:
        return self.connection


def test_liveness_does_not_require_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_versioned_health_endpoint():
    response = get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}


def test_readiness_succeeds_when_database_query_succeeds():
    connection = FakeConnection()
    application = create_app(Settings())
    application.state.db_engine = FakeEngine(connection)

    response = get("/health/ready", application)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert str(connection.statement) == "SELECT 1"


def test_readiness_fails_when_database_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = create_app(Settings())

    response = get("/health/ready", application)

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "service_unavailable",
        "message": "The request could not be completed.",
    }
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_readiness_fails_when_database_connection_fails():
    connection = FakeConnection(error=SQLAlchemyError("connection refused"))
    application = create_app(Settings())
    application.state.db_engine = FakeEngine(connection)

    response = get("/health/ready", application)

    assert response.status_code == 503
    assert "connection refused" not in response.text


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


def test_readiness_uses_application_database_engine():
    connection = FakeConnection()
    application = create_app(Settings())
    engine = FakeEngine(connection)
    application.state.db_engine = engine

    response = get("/health/ready", application)

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert engine.connection is connection
    assert str(connection.statement) == "SELECT 1"
