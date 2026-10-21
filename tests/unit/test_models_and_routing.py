"""
tests/unit/test_models_and_routing.py

Unit tests for Archis Samanta's ML/DL components:
- Model Client protocol & Mock implementation
- Markdown JSON stripping and schema validation
- IntentRouter classification with Nemotron Mini
- Policy invariance: Schemas forbid model-supplied authorization claims
"""

from __future__ import annotations

import unittest
import uuid
from pydantic import ValidationError

from cortexstone.agent.models.interface import (
    ModelRole,
    Role,
    ModelMessage,
    ModelTimeoutError,
    ModelSchemaValidationError,
)
from cortexstone.agent.models.mock import MockModelClient
from cortexstone.agent.models.nebius import NebiusTokenFactoryClient
from cortexstone.agent.schemas.routing import (
    IntentCategory,
    ComplexityLevel,
    RouteDecision,
)
from cortexstone.agent.schemas.actions import (
    ProposedAction,
    AgentPlan,
)
from cortexstone.agent.orchestration.router import IntentRouter


class TestModelClientAndRouting(unittest.IsolatedAsyncioTestCase):
    async def test_mock_model_client_generation(self):
        client = MockModelClient(fixed_text="Hello from mock")
        messages = [ModelMessage(role=Role.USER, content="Hello")]
        response = await client.generate(messages)

        self.assertEqual(response.raw_content, "Hello from mock")
        self.assertEqual(len(client.recorded_calls), 1)
        self.assertEqual(client.recorded_calls[0]["messages"][0].content, "Hello")

    async def test_mock_model_client_parsed_schema(self):
        fixture = RouteDecision(
            intent=IntentCategory.MEMORY_RECALL,
            complexity=ComplexityLevel.LOW,
            needs_reasoner=False,
            extracted_entities=["project status"],
            rationale="User is asking for past meeting notes",
        )
        client = MockModelClient(parsed_fixture=fixture)
        messages = [ModelMessage(role=Role.USER, content="What did we discuss last week?")]
        response = await client.generate_for_role(
            role=ModelRole.ROUTER,
            messages=messages,
            schema=RouteDecision,
        )

        self.assertIsNotNone(response.parsed)
        self.assertEqual(response.parsed.intent, IntentCategory.MEMORY_RECALL)
        self.assertFalse(response.parsed.needs_reasoner)

    def test_json_markdown_stripping_and_validation(self):
        markdown_json = """```json
        {
            "intent": "tool_action",
            "complexity": "high",
            "needs_reasoner": true,
            "extracted_entities": ["repo/fix"],
            "rationale": "Create pull request requires external tool"
        }
        ```"""
        validated = NebiusTokenFactoryClient._parse_and_validate(markdown_json, RouteDecision)
        self.assertEqual(validated.intent, IntentCategory.TOOL_ACTION)
        self.assertEqual(validated.complexity, ComplexityLevel.HIGH)
        self.assertTrue(validated.needs_reasoner)

    def test_invalid_json_raises_schema_validation_error(self):
        bad_json = "This is not json at all."
        with self.assertRaises(ModelSchemaValidationError):
            NebiusTokenFactoryClient._parse_and_validate(bad_json, RouteDecision)

    def test_schema_invariant_forbids_authorization_injection(self):
        """
        ARCHITECTURAL INVARIANT:
        The model proposes; backend decides.
        Models must not supply fields like is_authorized or risk_level.
        """
        # ProposedAction must forbid unknown fields
        payload = {
            "tool_name": "github.create_draft_pr",
            "target_ref": "owner/repo",
            "purpose": "Fix bug",
            "is_authorized": True,  # Forbidden field!
        }
        with self.assertRaises(ValidationError):
            ProposedAction.model_validate(payload)

    async def test_intent_router_success(self):
        fixture = RouteDecision(
            intent=IntentCategory.GUARDIAN_SCAN,
            complexity=ComplexityLevel.MEDIUM,
            needs_reasoner=True,
            extracted_entities=["cortexstone/repo"],
            rationale="User requested secret scan on repository",
        )
        client = MockModelClient(parsed_fixture=fixture)
        router = IntentRouter(model_client=client)

        decision = await router.route("Scan cortexstone/repo for exposed secrets")
        self.assertEqual(decision.intent, IntentCategory.GUARDIAN_SCAN)
        self.assertTrue(decision.needs_reasoner)

    async def test_intent_router_fallback_on_error(self):
        client = MockModelClient(simulate_error=ModelTimeoutError("Timed out"))
        router = IntentRouter(model_client=client)

        decision = await router.route("Do something complex")
        # Should gracefully return a fallback decision without crashing
        self.assertEqual(decision.intent, IntentCategory.CLARIFICATION)
        self.assertTrue(decision.needs_reasoner)


if __name__ == "__main__":
    unittest.main()
