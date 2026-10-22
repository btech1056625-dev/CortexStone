import pytest
from unittest.mock import AsyncMock, patch

from cortexstone.agent.orchestration.orchestrator import AgentOrchestrator
from cortexstone.agent.models.interface import ModelTimeoutError
from cortexstone.agent.schemas.routing import RouteDecision
from cortexstone.agent.models import MockModelClient


@pytest.mark.asyncio
async def test_orchestrator_returns_agent_plan():
    # Setup the mock client to return a valid ProposedAction
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
            "requires_user_approval": True,
        }
    )

    orchestrator = AgentOrchestrator(model_client=mock_client)
    
    # Patch the IntentRouter so it triggers the Reasoner model block
    with patch.object(orchestrator.router, "route", new_callable=AsyncMock) as mock_route:
        # Added the required 'rationale' field to pass Pydantic validation
        mock_route.return_value = RouteDecision(
            intent="tool_action", 
            needs_reasoner=True, 
            complexity="high",
            rationale="Routing to reasoner for tool action"
        )
        
        # Pass the required 'context' parameter
        res = await orchestrator.run("Fix the secret leak", context=[])
        
    # Assert the response is exactly what the PolicyEngine expects (List of actions)
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0].tool_name == "github.create_draft_pr"


@pytest.mark.asyncio
async def test_orchestrator_handles_timeout():
    # Setup mock to simulate a failure
    mock_client = MockModelClient(simulate_error=ModelTimeoutError("Timeout"))
    
    # Initialize without the old max_retries/timeout arguments
    orchestrator = AgentOrchestrator(model_client=mock_client)
    
    with patch.object(orchestrator.router, "route", new_callable=AsyncMock) as mock_route:
        # Added the required 'rationale' field to pass Pydantic validation
        mock_route.return_value = RouteDecision(
            intent="tool_action", 
            needs_reasoner=True, 
            complexity="high",
            rationale="Routing to reasoner to trigger timeout"
        )
        
        # The new spec safely returns an empty list when execution fails
        res = await orchestrator.run("Trigger timeout", context=[])
        
    assert res == []