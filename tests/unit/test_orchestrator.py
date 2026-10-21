import pytest
from cortexstone.agent.models.mock import MockModelClient
from cortexstone.agent.models.interface import ModelTimeoutError
from cortexstone.agent.orchestration.orchestrator import AgentOrchestrator

@pytest.mark.asyncio
async def test_orchestrator_returns_agent_plan():
    mock_client = MockModelClient(
        parsed_fixture={
            "summary": "Fixing the leaked security key",
            "actions": [{
                "tool_name": "github.create_draft_pr",
                "target_ref": "owner/repo",
                "arguments": {"branch": "fix/guardian-123"},
                "purpose": "Propose a reviewed remediation"
            }],
            "requires_user_approval": True
        }
    )
    
    orchestrator = AgentOrchestrator(model_client=mock_client)
    res = await orchestrator.run("Fix the secret leak")
    
    assert not res.is_error
    assert res.plan is not None
    assert res.plan.summary == "Fixing the leaked security key"
    assert len(res.plan.actions) == 1
    
    action = res.plan.actions[0]
    assert action.tool_name == "github.create_draft_pr"
    assert action.target_ref == "owner/repo"
    assert action.purpose == "Propose a reviewed remediation"

@pytest.mark.asyncio
async def test_orchestrator_handles_timeout():
    mock_client = MockModelClient(simulate_error=ModelTimeoutError("Timeout"))
    orchestrator = AgentOrchestrator(model_client=mock_client, max_retries=1, timeout_seconds=0.1)
    
    res = await orchestrator.run("Simulate a slow request")
    
    assert res.is_error
    assert "timed out" in res.error_message