from unittest.mock import AsyncMock, patch

import pytest

from cortexstone.agent.orchestration.orchestrator import AgentOrchestrator
from cortexstone.agent.schemas.actions import AgentPlan, ProposedAction
from cortexstone.agent.schemas.routing import IntentCategory, RouteDecision


class MockModelResponse:
    """Mock container representing the structured LLM response."""

    def __init__(self, plan_dict: dict):
        # Instantiate AgentPlan from dict so .parsed has real attributes
        self.parsed = AgentPlan(**plan_dict) if plan_dict else None
        self.raw_content = "{}"


class MockModelClient:
    """Mock client simulating model responses for orchestration tests."""

    def __init__(self, parsed_fixture: dict | None = None):
        self.parsed_fixture = parsed_fixture or {}

    async def generate_for_role(self, **kwargs) -> MockModelResponse:
        return MockModelResponse(self.parsed_fixture)

    async def agenerate_structured(self, **kwargs) -> MockModelResponse:
        return MockModelResponse(self.parsed_fixture)


@pytest.mark.asyncio
async def test_orchestrator_returns_agent_plan():
    # Setup mock return data with valid AgentPlan fields
    mock_client = MockModelClient(
        parsed_fixture={
            "summary": "Fixing the leaked security key",
            "actions": [
                {
                    "tool_name": "github.create_draft_pr",
                    "target_ref": "owner/repo",
                    "arguments": {"branch": "fix/guardian-123"},
                    "purpose": "Propose a reviewed remediation",
                }
            ],
        }
    )

    orchestrator = AgentOrchestrator(model_client=mock_client)

    # Patch the IntentRouter so it triggers the Reasoner model block
    with patch.object(orchestrator.router, "route", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = RouteDecision(
            intent=IntentCategory.TOOL_ACTION,
            needs_reasoner=True,
            complexity="high",
            rationale="Routing to reasoner for tool action",
        )

        res = await orchestrator.run("Fix the secret leak", context=[])

    # Assert the response is a list of proposed actions
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0].tool_name == "github.create_draft_pr"


@pytest.mark.asyncio
async def test_orchestrator_direct_chat_returns_empty_actions():
    mock_client = MockModelClient()
    orchestrator = AgentOrchestrator(model_client=mock_client)

    with patch.object(orchestrator.router, "route", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = RouteDecision(
            intent=IntentCategory.DIRECT_CHAT,
            needs_reasoner=False,
            complexity="low",
            rationale="Direct conversational request",
        )

        res = await orchestrator.run("Hello, how are you?", context=[])

    assert isinstance(res, list)
    assert len(res) == 0