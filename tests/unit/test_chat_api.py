"""Tests for authenticated chat and its memory-context boundary."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from cortexstone.agent.models import MockModelClient
from cortexstone.agent.models.interface import ModelSchemaValidationError
from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_authenticated_user,
    get_memory_service,
    get_model_client,
    get_policy_principal,
)
from cortexstone.api.main import create_app
from cortexstone.memory.embeddings.config import EmbeddingProviderError
from cortexstone.memory.retrieval.retriever import RetrievalResult
from cortexstone.memory.schemas import (
    MemoryItemRead,
    MemoryKind,
    MemorySearchResult,
    SensitivityLevel,
)
from cortexstone.security.policy import PolicyPrincipal


def memory_result(
    content: str,
    *,
    kind: MemoryKind = MemoryKind.FACT,
    sensitivity: SensitivityLevel = SensitivityLevel.NORMAL,
    approved: bool = False,
    deleted: bool = False,
    inferred: bool = False,
) -> MemorySearchResult:
    now = datetime.now(UTC)
    memory = MemoryItemRead(
        id=uuid4(),
        owner_id="verified-subject",
        kind=kind,
        content=content,
        occurred_at=None,
        sensitivity=sensitivity,
        metadata={"is_inferred": inferred},
        source_type="user",
        source_ref="chat-test",
        confidence=1.0,
        approved=approved,
        deleted_at=now if deleted else None,
        created_at=now,
        updated_at=now,
    )
    return MemorySearchResult(item=memory, relevance_score=0.9)


def make_chat_app(retrieval_items, model_client):
    application = create_app()
    memory_service = AsyncMock()
    memory_service.search_memories.return_value = RetrievalResult(
        owner_id="verified-subject",
        query="What did I decide?",
        total_eligible=len(retrieval_items),
        returned_count=len(retrieval_items),
        items=retrieval_items,
    )
    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject="verified-subject",
        display_name="Verified User",
    )
    application.dependency_overrides[get_memory_service] = lambda: memory_service
    application.dependency_overrides[get_model_client] = lambda: model_client
    return application, memory_service


def test_chat_retrieves_owner_context_filters_and_returns_validated_response():
    permitted = memory_result("We chose PostgreSQL for the service.", inferred=True)
    sensitive = memory_result(
        "Sensitive note must not be sent.",
        sensitivity=SensitivityLevel.SENSITIVE,
    )
    unapproved_skill = memory_result(
        "Unapproved skill must not be sent.",
        kind=MemoryKind.SKILL,
    )
    approved_skill = memory_result(
        "Approved skill may be sent.",
        kind=MemoryKind.SKILL,
        approved=True,
    )
    other_owner = memory_result("Another owner's memory must not be sent.")
    other_owner.item.owner_id = "another-subject"
    deleted = memory_result("Deleted memory must not be sent.", deleted=True)
    model_client = MockModelClient(
        parsed_fixture={
            "conversation_id": "model-controlled-id",
            "answer": "We chose PostgreSQL.",
        }
    )
    application, memory_service = make_chat_app(
        [permitted, sensitive, unapproved_skill, approved_skill, other_owner, deleted],
        model_client,
    )

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/v1/chat",
                json={"message": "What did I decide?", "conversation_id": "conversation_1"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "conversation_1",
        "answer": "We chose PostgreSQL.",
        "proposed_actions": [],
    }
    memory_service.search_memories.assert_awaited_once()
    search_call = memory_service.search_memories.await_args.kwargs
    assert search_call["owner_id"] == "verified-subject"
    assert search_call["query"] == "What did I decide?"
    assert search_call["sensitivity"] == SensitivityLevel.NORMAL
    assert search_call["top_k"] == 5

    user_content = model_client.recorded_calls[0]["messages"][1].content
    assert "We chose PostgreSQL for the service." in user_content
    assert "[Source: user:chat-test," in user_content
    assert "[INFERRED]" in user_content
    assert "Approved skill may be sent." in user_content
    system_content = model_client.recorded_calls[0]["messages"][0].content
    assert (
        "Cite each recalled fact using its exact source reference and timestamp." in system_content
    )
    assert "records as uncertain" in system_content
    assert "Sensitive note must not be sent." not in user_content
    assert "Unapproved skill must not be sent." not in user_content
    assert "Another owner's memory must not be sent." not in user_content
    assert "Deleted memory must not be sent." not in user_content


def test_chat_returns_bad_gateway_when_model_response_is_not_parsed():
    application, _ = make_chat_app([], MockModelClient(fixed_text="not validated"))

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "Hello"})

    response = asyncio.run(send_request())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_response"


def test_chat_maps_invalid_model_json_to_bad_gateway():
    model_client = MockModelClient(
        simulate_error=ModelSchemaValidationError("invalid structured response")
    )
    application, _ = make_chat_app([], model_client)

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "Hello"})

    response = asyncio.run(send_request())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_response"


def test_chat_does_not_call_model_when_memory_retrieval_fails():
    model_client = MockModelClient()
    application, memory_service = make_chat_app([], model_client)
    memory_service.search_memories.side_effect = EmbeddingProviderError("provider offline")

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "What did I decide?"})

    response = asyncio.run(send_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert model_client.recorded_calls == []


def test_chat_fails_closed_when_model_provider_is_not_configured():
    application = create_app()
    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject="verified-subject",
        display_name="Verified User",
    )
    application.dependency_overrides[get_memory_service] = lambda: AsyncMock()
    application.state.model_client = None

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "Hello"})

    response = asyncio.run(send_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_chat_fails_closed_without_authentication():
    application = create_app()

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "Hello"})

    response = asyncio.run(send_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_chat_returns_only_typed_unexecuted_action_proposals():
    model_client = MockModelClient(
        parsed_fixture={
            "proposed_actions": [
                {
                    "tool_name": "notes.search",
                    "target_ref": "notes/personal",
                    "arguments": {"query": "deployment plan"},
                    "purpose": "Find the user's deployment plan.",
                }
            ]
        }
    )
    application, _ = make_chat_app([], model_client)

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "Find my plan"})

    response = asyncio.run(send_request())

    assert response.status_code == 200
    action_data = response.json()["proposed_actions"][0]
    action = ProposedAction.model_validate(action_data)
    assert action.tool_name == "notes.search"
    assert action.target_ref == "notes/personal"
    assert model_client.recorded_calls[0]["schema"].__name__ == "ChatResult"


def test_chat_rejects_principal_that_does_not_match_verified_identity():
    application, memory_service = make_chat_app([], MockModelClient())
    application.dependency_overrides[get_policy_principal] = lambda: PolicyPrincipal(
        principal_id="different-subject",
        grants=(),
    )

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json={"message": "Hello"})

    response = asyncio.run(send_request())

    assert response.status_code == 403
    memory_service.search_memories.assert_not_awaited()


def test_chat_route_is_listed_in_openapi():
    application = create_app()

    assert application.openapi()["paths"]["/api/v1/chat"]["post"]["responses"]["200"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": " "},
        {"message": "Hello", "unexpected": True},
    ],
)
def test_chat_rejects_invalid_request_payloads(payload):
    application, _ = make_chat_app([], MockModelClient(parsed_fixture={"answer": "Hi"}))

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/chat", json=payload)

    response = asyncio.run(send_request())

    assert response.status_code == 422
