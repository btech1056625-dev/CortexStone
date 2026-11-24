"""Tests for separate Groq routing and Google AI Studio reasoning providers."""

from __future__ import annotations

import asyncio
import json

import httpx

from cortexstone.agent.models.interface import ModelError, ModelMessage, ModelRole, Role
from cortexstone.agent.models.split import SplitModelClient
from cortexstone.agent.orchestration.orchestrator import AgentOrchestrator
from cortexstone.application.chat.schemas import ChatResult


def test_split_client_routes_roles_to_separate_providers():
    recorded: list[httpx.Request] = []

    def handle_router(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    def handle_reasoner(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_router)) as router_http:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handle_reasoner)
            ) as reasoner_http:
                client = SplitModelClient(
                    groq_api_key="groq-test-key",
                    groq_model_id="groq-router",
                    google_api_key="google-test-key",
                    google_model_id="gemini-reasoner",
                    router_client=router_http,
                    reasoner_client=reasoner_http,
                )
                router_response = await client.generate_for_role(
                    role=ModelRole.ROUTER,
                    messages=[ModelMessage(role=Role.USER, content="route")],
                )
                reasoner_response = await client.generate_for_role(
                    role=ModelRole.REASONER,
                    messages=[ModelMessage(role=Role.USER, content="reason")],
                )

                assert router_response.model_id == "groq-router"
                assert reasoner_response.model_id == "gemini-reasoner"

    asyncio.run(run())
    assert len(recorded) == 2
    assert json.loads(recorded[0].content)["model"] == "groq-router"
    assert json.loads(recorded[1].content)["model"] == "gemini-reasoner"


def test_groq_only_client_handles_simple_chat_without_google_request():
    recorded: list[httpx.Request] = []

    def handle_router(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        payload = json.loads(request.content)
        if payload.get("response_format") == {"type": "json_object"}:
            if "Intent and Complexity Router" in payload["messages"][0]["content"]:
                content = json.dumps(
                    {
                        "intent": "direct_chat",
                        "complexity": "low",
                        "needs_reasoner": False,
                        "rationale": "This is simple conversation.",
                    }
                )
            else:
                content = json.dumps({"answer": "Hello from Groq."})
        else:
            content = "Hello."
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_router)) as router_http:
            client = SplitModelClient(
                groq_api_key="groq-test-key",
                groq_model_id="groq-router",
                router_client=router_http,
            )
            response = await AgentOrchestrator(client).generate_chat_response(
                user_message="Hello",
                messages=[ModelMessage(role=Role.USER, content="Hello")],
                schema=ChatResult,
            )

            assert response.parsed is not None
            assert response.parsed.answer == "Hello from Groq."
            assert response.model_id == "groq-router"
            try:
                await client.generate_for_role(
                    role=ModelRole.REASONER,
                    messages=[ModelMessage(role=Role.USER, content="Reason")],
                )
            except ModelError as error:
                assert "not configured" in str(error)
            else:
                raise AssertionError("Reasoner request must fail without Google configuration")

    asyncio.run(run())
    assert len(recorded) == 2
    assert all("api.groq.com" in str(request.url) for request in recorded)
