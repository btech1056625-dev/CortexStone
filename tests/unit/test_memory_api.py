"""Tests for owner-scoped memory HTTP routes."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import get_authenticated_user, get_db_session, get_memory_service
from cortexstone.api.main import create_app
from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.embeddings.bge import BGEEmbeddingProvider
from cortexstone.memory.schemas import MemoryItemRead


class CapturingMemoryService:
    def __init__(self):
        self.owner_ids: list[str] = []

    async def create_memory(self, owner_id, item):
        self.owner_ids.append(owner_id)
        now = datetime.now(UTC)
        return MemoryItemRead(
            id=uuid4(),
            owner_id=owner_id,
            kind=item.kind,
            title=item.title,
            content=item.content,
            occurred_at=item.occurred_at,
            sensitivity=item.sensitivity,
            metadata=item.metadata,
            source_type=item.source_type,
            source_ref=item.source_ref,
            confidence=item.confidence,
            approved=False,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )

    async def get_memory(self, owner_id, memory_id):
        self.owner_ids.append(owner_id)
        return None


def configured_app():
    application = create_app()
    memory_service = CapturingMemoryService()
    session = AsyncMock()

    async def provide_session():
        yield session

    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject="verified-subject",
        display_name="Verified User",
    )
    application.dependency_overrides[get_memory_service] = lambda: memory_service
    application.dependency_overrides[get_db_session] = provide_session
    return application, memory_service, session


def test_memory_create_uses_authenticated_subject_and_forbids_owner_input():
    application, memory_service, session = configured_app()

    async def send_requests():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            created = await client.post(
                "/api/v1/memories",
                json={
                    "memory_type": "fact",
                    "content": "Only the authenticated owner owns this.",
                },
            )
            spoofed = await client.post(
                "/api/v1/memories",
                json={
                    "memory_type": "fact",
                    "content": "Attempted owner override.",
                    "owner_id": "attacker-selected-owner",
                },
            )
            return created, spoofed

    created, spoofed = asyncio.run(send_requests())

    assert created.status_code == 201
    assert created.json()["memory_type"] == "fact"
    assert created.json()["source"] == "user"
    assert created.json()["confidence"] == 1.0
    assert "owner_id" not in created.json()
    assert memory_service.owner_ids == ["verified-subject"]
    assert session.commit.await_count == 1
    assert spoofed.status_code == 422


def test_memory_create_uses_sqlalchemy_repository_and_request_session():
    application = create_app()
    session = AsyncMock()
    embedding = [0.1] * 384
    application.state.memory_embedding_provider = AsyncMock()
    application.state.memory_embedding_provider.embed_document.return_value = embedding
    persisted_models = []
    session.add = Mock(side_effect=persisted_models.append)

    async def flush_model():
        model = persisted_models[-1]
        now = datetime.now(UTC)
        model.id = uuid4()
        model.created_at = now
        model.updated_at = now

    session.flush.side_effect = flush_model

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject="verified-subject",
        display_name="Verified User",
    )
    application.state.db_session_factory = SessionContext

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/v1/memories",
                json={
                    "memory_type": "fact",
                    "content": "Persist through the configured repository.",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 201
    assert len(persisted_models) == 1
    assert isinstance(persisted_models[0], MemoryItemModel)
    assert persisted_models[0].owner_id == "verified-subject"
    assert persisted_models[0].content == "Persist through the configured repository."
    assert persisted_models[0].embedding == embedding
    application.state.memory_embedding_provider.embed_document.assert_awaited_once_with(
        "Persist through the configured repository."
    )
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()


def test_application_uses_existing_lazy_bge_embedding_provider():
    application = create_app()

    assert isinstance(application.state.memory_embedding_provider, BGEEmbeddingProvider)


def test_memory_owned_by_another_subject_is_not_disclosed():
    application, memory_service, _ = configured_app()
    memory_id = uuid4()

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(f"/api/v1/memories/{memory_id}")

    response = asyncio.run(send_request())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert memory_service.owner_ids == ["verified-subject"]


def test_memory_owned_by_another_subject_cannot_be_forgotten():
    application, memory_service, session = configured_app()
    memory_service.forget_memory = AsyncMock(
        return_value=type("Receipt", (), {"status": "not_found"})()
    )
    memory_id = uuid4()

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.delete(f"/api/v1/memories/{memory_id}")

    response = asyncio.run(send_request())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    memory_service.forget_memory.assert_awaited_once_with(
        owner_id="verified-subject",
        memory_id=memory_id,
    )
    session.commit.assert_not_awaited()


def test_memory_update_is_not_exposed():
    application, _, _ = configured_app()
    memory_id = uuid4()

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.patch(
                f"/api/v1/memories/{memory_id}",
                json={"content": "Try to alter another user's memory."},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 405


def test_memory_search_export_and_patch_are_not_public_contract_routes():
    application, _, _ = configured_app()

    paths = application.openapi()["paths"]

    assert "/api/v1/me" in paths
    assert "/api/v1/users/me" not in paths
    assert "/health" in paths
    assert "/ready" in paths
    assert "/api/v1/memories" in paths
    assert set(paths["/api/v1/memories"]) == {"get", "post"}
    assert set(paths["/api/v1/memories/{memory_id}"]) == {"get", "delete"}
    assert "/api/v1/memories/search" not in paths
    assert "/api/v1/memories/export" not in paths
    assert "patch" not in paths["/api/v1/memories/{memory_id}"]


def test_memory_list_returns_contract_page_envelope():
    application, memory_service, _ = configured_app()
    memory_service.list_memories = AsyncMock(return_value=[])
    memory_service.count_memories = AsyncMock(return_value=7)

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get("/api/v1/memories?limit=5&offset=2")

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 7, "limit": 5, "offset": 2}
    memory_service.list_memories.assert_awaited_once()
    memory_service.count_memories.assert_awaited_once()


def test_memory_delete_returns_no_content():
    application, memory_service, session = configured_app()
    memory_service.forget_memory = AsyncMock(
        return_value=type("Receipt", (), {"status": "forgotten"})()
    )
    memory_id = uuid4()

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.delete(f"/api/v1/memories/{memory_id}")

    response = asyncio.run(send_request())

    assert response.status_code == 204
    assert response.content == b""
    assert session.commit.await_count == 1
