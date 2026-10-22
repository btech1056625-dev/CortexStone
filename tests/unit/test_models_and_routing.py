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
from datetime import UTC

from pydantic import ValidationError

from cortexstone.agent.models.interface import (
    ModelMessage,
    ModelRole,
    ModelSchemaValidationError,
    ModelTimeoutError,
    Role,
)
from cortexstone.agent.models.mock import MockModelClient
from cortexstone.agent.models.nebius import NebiusTokenFactoryClient
from cortexstone.agent.orchestration.router import IntentRouter
from cortexstone.agent.schemas.actions import (
    AgentPlan,
    ProposedAction,
)
from cortexstone.agent.schemas.routing import (
    ComplexityLevel,
    IntentCategory,
    RouteDecision,
)


class TestModelClientAndRouting(unittest.IsolatedAsyncioTestCase):
    async def test_mock_model_client_generation(self):
        # Verify raw mock responses and recorded request messages.
        client = MockModelClient(fixed_text="Hello from mock")
        messages = [ModelMessage(role=Role.USER, content="Hello")]
        response = await client.generate(messages)

        self.assertEqual(response.raw_content, "Hello from mock")
        self.assertEqual(len(client.recorded_calls), 1)
        self.assertEqual(client.recorded_calls[0]["messages"][0].content, "Hello")

    async def test_mock_model_client_parsed_schema(self):
        # A parsed fixture should be returned as the requested Pydantic schema.
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
        # The parser should accept JSON wrapped in a Markdown code fence.
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

    def test_plain_json_is_parsed_and_validated(self):
        plain_json = """
        {
            "intent": "direct_chat",
            "complexity": "low",
            "needs_reasoner": false,
            "extracted_entities": [],
            "rationale": "The user asked a simple question"
        }
        """

        validated = NebiusTokenFactoryClient._parse_and_validate(plain_json, RouteDecision)

        self.assertEqual(validated.intent, IntentCategory.DIRECT_CHAT)
        self.assertEqual(validated.complexity, ComplexityLevel.LOW)
        self.assertFalse(validated.needs_reasoner)

    def test_invalid_json_raises_schema_validation_error(self):
        # Malformed model output must surface as the client-specific validation error.
        bad_json = "This is not json at all."
        with self.assertRaises(ModelSchemaValidationError):
            NebiusTokenFactoryClient._parse_and_validate(bad_json, RouteDecision)

    def test_schema_invariant_forbids_authorization_injection(self):
        """
        ARCHITECTURAL INVARIANT:
        The model proposes; backend decides.
        Models must not supply fields like is_authorized or risk_level.
        """
        # Backend authorization fields are excluded from model-proposed actions.
        payload = {
            "tool_name": "github.create_draft_pr",
            "target_ref": "owner/repo",
            "purpose": "Fix bug",
            "is_authorized": True,  # Forbidden field!
        }
        with self.assertRaises(ValidationError):
            ProposedAction.model_validate(payload)

    def test_valid_proposed_action_is_accepted(self):
        # A proposal containing every required field should produce a typed action.
        action = ProposedAction(
            tool_name="notes.search",
            target_ref="project-notes",
            purpose="Find notes related to the project",
        )

        # Check both user-supplied values and server-generated metadata.
        self.assertEqual(action.tool_name, "notes.search")
        self.assertEqual(action.target_ref, "project-notes")
        self.assertEqual(action.purpose, "Find notes related to the project")
        self.assertIsNotNone(action.action_id)
        self.assertIsNotNone(action.requested_at)

    def test_proposed_action_requires_tool_name(self):
        # An action without a tool cannot be checked or dispatched safely.
        payload = {
            "target_ref": "owner/repo",
            "purpose": "Scan the repository",
        }

        # Missing required fields must fail at the schema boundary.
        with self.assertRaises(ValidationError):
            ProposedAction.model_validate(payload)

    def test_proposed_action_requires_target_ref(self):
        # Policy cannot authorize an action unless its exact target is known.
        payload = {
            "tool_name": "guardian.scan",
            "purpose": "Scan the repository",
        }

        with self.assertRaises(ValidationError):
            ProposedAction.model_validate(payload)

    def test_proposed_action_requires_purpose(self):
        # Every proposed side effect needs a truthful, user-visible reason.
        payload = {
            "tool_name": "guardian.scan",
            "target_ref": "owner/repo",
        }

        with self.assertRaises(ValidationError):
            ProposedAction.model_validate(payload)

    def test_proposed_action_forbids_model_supplied_risk_level(self):
        # Risk is derived by backend policy and must never be chosen by the model.
        payload = {
            "tool_name": "github.create_draft_pr",
            "target_ref": "owner/repo",
            "purpose": "Create a proposed security fix",
            "risk_level": "safe",
        }

        # ProposedAction forbids unknown fields, including model-supplied risk claims.
        with self.assertRaises(ValidationError):
            ProposedAction.model_validate(payload)

    def test_valid_json_with_invalid_route_schema_is_rejected(self):
        # This text is valid JSON but omits required RouteDecision fields.
        incomplete_json = """
        {
            "intent": "tool_action"
        }
        """

        # Schema failures should use the model layer's predictable exception type.
        with self.assertRaises(ModelSchemaValidationError):
            NebiusTokenFactoryClient._parse_and_validate(
                incomplete_json,
                RouteDecision,
            )

    def test_invalid_route_enum_values_are_rejected(self):
        payloads = (
            """
            {
                "intent": "made_up_intent",
                "complexity": "low",
                "needs_reasoner": false,
                "extracted_entities": [],
                "rationale": "Invalid intent"
            }
            """,
            """
            {
                "intent": "direct_chat",
                "complexity": "extreme",
                "needs_reasoner": false,
                "extracted_entities": [],
                "rationale": "Invalid complexity"
            }
            """,
        )

        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ModelSchemaValidationError):
                NebiusTokenFactoryClient._parse_and_validate(payload, RouteDecision)

    def test_route_decision_rejects_extra_authorization_field(self):
        payload = """
        {
            "intent": "tool_action",
            "complexity": "medium",
            "needs_reasoner": true,
            "extracted_entities": ["owner/repo"],
            "rationale": "A tool action was requested",
            "is_authorized": true
        }
        """

        with self.assertRaises(ModelSchemaValidationError):
            NebiusTokenFactoryClient._parse_and_validate(payload, RouteDecision)

    def test_agent_plan_accepts_five_actions(self):
        # Five actions are the documented upper boundary for one planning cycle.
        actions = [
            ProposedAction(
                tool_name="notes.search",
                target_ref=f"note-{index}",
                purpose="Search an authorized note",
            )
            for index in range(5)
        ]

        plan = AgentPlan(summary="Search five notes", actions=actions)

        self.assertEqual(len(plan.actions), 5)

    def test_agent_plan_rejects_more_than_five_actions(self):
        # Six actions exceed the bounded-plan limit and must be rejected.
        actions = [
            ProposedAction(
                tool_name="notes.search",
                target_ref=f"note-{index}",
                purpose="Search an authorized note",
            )
            for index in range(6)
        ]

        with self.assertRaises(ValidationError):
            AgentPlan(summary="An oversized plan", actions=actions)

    def test_agent_plan_rejects_backend_policy_field(self):
        payload = {
            "summary": "A model-generated plan",
            "actions": [],
            "policy_approved": True,
        }

        with self.assertRaises(ValidationError):
            AgentPlan.model_validate(payload)

    def test_proposed_actions_receive_unique_ids(self):
        first = ProposedAction(
            tool_name="notes.search",
            target_ref="first-note",
            purpose="Search the first note",
        )
        second = ProposedAction(
            tool_name="notes.search",
            target_ref="second-note",
            purpose="Search the second note",
        )

        self.assertNotEqual(first.action_id, second.action_id)

    def test_proposed_action_timestamp_is_utc(self):
        action = ProposedAction(
            tool_name="notes.search",
            target_ref="project-notes",
            purpose="Search project notes",
        )

        self.assertIsNotNone(action.requested_at.tzinfo)
        self.assertEqual(action.requested_at.utcoffset(), UTC.utcoffset(action.requested_at))

    async def test_intent_router_success(self):
        # A valid model decision should pass through the router unchanged.
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
        # A model timeout should produce a safe clarification decision.
        client = MockModelClient(simulate_error=ModelTimeoutError("Timed out"))
        router = IntentRouter(model_client=client)

        decision = await router.route("Do something complex")
        # Should gracefully return a fallback decision without crashing
        self.assertEqual(decision.intent, IntentCategory.CLARIFICATION)
        self.assertTrue(decision.needs_reasoner)

    async def test_intent_router_handles_empty_input(self):
        # Blank input should be handled locally instead of spending a provider call.
        client = MockModelClient()
        router = IntentRouter(model_client=client)

        decision = await router.route("   ")

        # The router should ask for clarification and classify the work as low complexity.
        self.assertEqual(decision.intent, IntentCategory.CLARIFICATION)
        self.assertEqual(decision.complexity, ComplexityLevel.LOW)
        self.assertFalse(decision.needs_reasoner)
        # No recorded call proves that the model provider was never contacted.
        self.assertEqual(len(client.recorded_calls), 0)

    async def test_intent_router_sends_bounded_structured_request(self):
        fixture = RouteDecision(
            intent=IntentCategory.GUARDIAN_SCAN,
            complexity=ComplexityLevel.MEDIUM,
            needs_reasoner=True,
            extracted_entities=["owner/repo"],
            rationale="A repository scan was requested",
        )
        client = MockModelClient(parsed_fixture=fixture)
        router = IntentRouter(model_client=client)

        await router.route("   Scan owner/repo   ")

        self.assertEqual(len(client.recorded_calls), 1)
        call = client.recorded_calls[0]
        self.assertEqual(call["model_id"], "mock-router")
        self.assertIs(call["schema"], RouteDecision)
        self.assertEqual(len(call["messages"]), 2)
        self.assertEqual(call["messages"][0].role, Role.SYSTEM)
        self.assertEqual(call["messages"][1].role, Role.USER)
        self.assertEqual(call["messages"][1].content, "Scan owner/repo")

    async def test_intent_router_falls_back_when_parsed_output_is_missing(self):
        client = MockModelClient(fixed_text="unstructured response")
        router = IntentRouter(model_client=client)

        decision = await router.route("Scan owner/repo")

        self.assertEqual(decision.intent, IntentCategory.CLARIFICATION)
        self.assertEqual(decision.complexity, ComplexityLevel.MEDIUM)
        self.assertTrue(decision.needs_reasoner)


if __name__ == "__main__":
    unittest.main()
