import asyncio

import httpx
from sqlalchemy.exc import SQLAlchemyError

from cortexstone.api.config import Settings
from cortexstone.api.main import app, create_app
from cortexstone.api.v1.router import MIGRATION_HEADS


def get(path: str, application=app) -> httpx.Response:
    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(send_request())


class FakeConnection:
    def __init__(
        self,
        error: Exception | None = None,
        migration_revisions: tuple[str, ...] = tuple(MIGRATION_HEADS),
        migration_error: Exception | None = None,
    ) -> None:
        self.error = error
        self.statements = []
        self.migration_revisions = migration_revisions
        self.migration_error = migration_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def execute(self, statement):
        self.statements.append(str(statement))
        if self.error is not None:
            raise self.error
        if "alembic_version" in str(statement):
            if self.migration_error is not None:
                raise self.migration_error
            return FakeResult(self.migration_revisions)
        return FakeResult()


class FakeResult:
    def __init__(self, rows: tuple[str, ...] = ()) -> None:
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


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
    assert connection.statements == [
        "SELECT 1",
        "SELECT version_num FROM alembic_version",
    ]


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


def test_readiness_fails_when_migrations_are_not_at_head():
    connection = FakeConnection(migration_revisions=("0001",))
    application = create_app(Settings())
    application.state.db_engine = FakeEngine(connection)

    response = get("/health/ready", application)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert connection.statements[-1] == "SELECT version_num FROM alembic_version"


def test_readiness_fails_when_migration_table_is_missing():
    connection = FakeConnection(migration_error=SQLAlchemyError("migration table missing"))
    application = create_app(Settings())
    application.state.db_engine = FakeEngine(connection)

    response = get("/health/ready", application)

    assert response.status_code == 503
    assert "migration table missing" not in response.text


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
    assert connection.statements == [
        "SELECT 1",
        "SELECT version_num FROM alembic_version",
    ]
