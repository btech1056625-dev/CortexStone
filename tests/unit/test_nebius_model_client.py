"""Unit tests for the Nebius Token Factory model adapter."""

from __future__ import annotations

import json
import unittest

import httpx

from cortexstone.agent.models.interface import (
    ModelAuthenticationError,
    ModelError,
    ModelMessage,
    ModelRateLimitError,
    ModelRole,
    ModelTimeoutError,
    Role,
)
from cortexstone.agent.models.nebius import NebiusTokenFactoryClient
from cortexstone.agent.schemas.routing import ComplexityLevel, IntentCategory, RouteDecision


class TestNebiusTokenFactoryClient(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def successful_response(content: str = "Hello from Nebius") -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                },
            },
        )

    async def test_generate_returns_successful_text_response(self):
        # Record requests so the test can prove that the adapter made exactly one call.
        recorded_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return httpx.Response(
                status_code=200,
                json={
                    "choices": [
                        {
                            "message": {"content": "Hello from Nebius"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                },
            )

        # MockTransport exercises the real adapter without making a network request.
        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(
                api_key="test-api-key",
                client=http_client,
            )

            response = await client.generate(
                messages=[ModelMessage(role=Role.USER, content="Hello")],
                model_id="test-model",
            )

        # The adapter should preserve the provider's content and response metadata.
        self.assertEqual(response.raw_content, "Hello from Nebius")
        self.assertEqual(response.model_id, "test-model")
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.usage.prompt_tokens, 10)
        self.assertEqual(response.usage.completion_tokens, 4)
        self.assertEqual(response.usage.total_tokens, 14)
        self.assertEqual(len(recorded_requests), 1)

    async def test_generate_parses_successful_structured_response(self):
        # Return valid JSON matching the RouteDecision schema as the model's text.
        recorded_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return httpx.Response(
                status_code=200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"intent":"tool_action","complexity":"medium",'
                                    '"needs_reasoner":true,"extracted_entities":'
                                    '["owner/repo"],"rationale":"A tool action was requested"}'
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {},
                },
            )

        # Supplying a schema asks the real adapter to parse and validate model output.
        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(
                api_key="test-api-key",
                client=http_client,
            )

            response = await client.generate(
                messages=[
                    ModelMessage(
                        role=Role.USER,
                        content="Create an action for owner/repo",
                    )
                ],
                schema=RouteDecision,
                model_id="test-router-model",
            )

        # Parsed output should be typed, allowing callers to avoid trusting raw JSON.
        self.assertIsInstance(response.parsed, RouteDecision)
        self.assertEqual(response.parsed.intent, IntentCategory.TOOL_ACTION)
        self.assertEqual(response.parsed.complexity, ComplexityLevel.MEDIUM)
        self.assertTrue(response.parsed.needs_reasoner)
        self.assertEqual(response.parsed.extracted_entities, ["owner/repo"])

        # Supplying a schema must ask the provider for a JSON object response.
        payload = json.loads(recorded_requests[0].content)
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    async def test_unstructured_request_omits_response_format(self):
        recorded_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return self.successful_response()

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(api_key="test-api-key", client=http_client)
            await client.generate(
                messages=[ModelMessage(role=Role.USER, content="Hello")],
                model_id="test-model",
            )

        payload = json.loads(recorded_requests[0].content)
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Hello"}])

    async def test_generate_for_router_role_uses_router_defaults(self):
        recorded_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return self.successful_response()

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(
                api_key="test-api-key",
                router_model_id="test-router",
                reasoner_model_id="test-reasoner",
                client=http_client,
            )
            response = await client.generate_for_role(
                role=ModelRole.ROUTER,
                messages=[ModelMessage(role=Role.USER, content="Route this")],
            )

        payload = json.loads(recorded_requests[0].content)
        self.assertEqual(payload["model"], "test-router")
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(response.model_id, "test-router")

    async def test_generate_for_reasoner_role_uses_reasoner_defaults(self):
        recorded_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return self.successful_response()

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(
                api_key="test-api-key",
                router_model_id="test-router",
                reasoner_model_id="test-reasoner",
                client=http_client,
            )
            response = await client.generate_for_role(
                role=ModelRole.REASONER,
                messages=[ModelMessage(role=Role.USER, content="Plan this")],
            )

        payload = json.loads(recorded_requests[0].content)
        self.assertEqual(payload["model"], "test-reasoner")
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(response.model_id, "test-reasoner")

    def test_empty_api_key_is_rejected(self):
        for api_key in ("", "   "):
            with self.subTest(api_key=api_key), self.assertRaises(ValueError):
                NebiusTokenFactoryClient(api_key=api_key)

    async def test_authentication_errors_are_normalized(self):
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                transport = httpx.MockTransport(
                    lambda request, code=status_code: httpx.Response(code)
                )
                async with httpx.AsyncClient(transport=transport) as http_client:
                    client = NebiusTokenFactoryClient(
                        api_key="secret-test-key",
                        client=http_client,
                    )

                    with self.assertRaises(ModelAuthenticationError) as raised:
                        await client.generate(
                            messages=[ModelMessage(role=Role.USER, content="private prompt")]
                        )

                self.assertNotIn("secret-test-key", str(raised.exception))
                self.assertNotIn("private prompt", str(raised.exception))

    async def test_rate_limit_error_is_normalized(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(429))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(api_key="test-api-key", client=http_client)

            with self.assertRaises(ModelRateLimitError):
                await client.generate(messages=[])

    async def test_server_error_is_normalized_without_response_body(self):
        sensitive_body = "provider leaked sensitive-response-data"
        transport = httpx.MockTransport(lambda request: httpx.Response(500, text=sensitive_body))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(api_key="test-api-key", client=http_client)

            with self.assertRaises(ModelError) as raised:
                await client.generate(messages=[])

        self.assertNotIn(sensitive_body, str(raised.exception))

    async def test_timeout_is_normalized(self):
        def raise_timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("provider timed out", request=request)

        transport = httpx.MockTransport(raise_timeout)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(api_key="test-api-key", client=http_client)

            with self.assertRaises(ModelTimeoutError):
                await client.generate(messages=[], timeout=0.5)

    async def test_connection_error_is_normalized(self):
        def raise_connection_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection failed", request=request)

        transport = httpx.MockTransport(raise_connection_error)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(api_key="test-api-key", client=http_client)

            with self.assertRaises(ModelError):
                await client.generate(messages=[])

    async def test_missing_usage_values_default_to_zero(self):
        def handle_request(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Hello"}}],
                    "usage": {},
                },
            )

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = NebiusTokenFactoryClient(api_key="test-api-key", client=http_client)
            response = await client.generate(messages=[])

        self.assertEqual(response.usage.prompt_tokens, 0)
        self.assertEqual(response.usage.completion_tokens, 0)
        self.assertEqual(response.usage.total_tokens, 0)


if __name__ == "__main__":
    unittest.main()
