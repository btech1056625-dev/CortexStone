import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from cortexstone.api.config import Settings
from cortexstone.api.dependencies import get_db_session
from cortexstone.api.main import create_app


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSessionContext:
        return FakeSessionContext(self.session)


def test_request_dependency_yields_and_closes_session():
    session = FakeSession()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_session_factory=FakeSessionFactory(session)))
    )

    async def consume_dependency() -> FakeSession:
        dependency = get_db_session(request)
        yielded_session = await anext(dependency)
        await dependency.aclose()
        return yielded_session

    yielded_session = asyncio.run(consume_dependency())

    assert yielded_session is session
    assert session.closed


def test_request_dependency_rolls_back_on_request_error():
    session = FakeSession()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_session_factory=FakeSessionFactory(session)))
    )

    async def trigger_error() -> None:
        dependency = get_db_session(request)
        await anext(dependency)
        with pytest.raises(ValueError, match="request failed"):
            await dependency.athrow(ValueError("request failed"))

    asyncio.run(trigger_error())

    assert session.rolled_back
    assert session.closed


def test_request_dependency_fails_when_database_is_not_configured():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_session_factory=None)))

    async def consume_dependency() -> None:
        dependency = get_db_session(request)
        with pytest.raises(HTTPException) as error:
            await anext(dependency)
        assert error.value.status_code == 503

    asyncio.run(consume_dependency())


def test_database_url_is_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

    assert Settings.from_environment().database_url == "postgresql://localhost/test"


def test_app_builds_application_scoped_engine_and_session_factory():
    application = create_app(Settings(database_url="postgresql://localhost/test"))
    engine = application.state.db_engine
    session_factory = application.state.db_session_factory

    try:
        assert engine.url.drivername == "postgresql+asyncpg"
        assert session_factory.kw["bind"] is engine
    finally:
        asyncio.run(engine.dispose())
