import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.security.policy import (
    ActionScope,
    ApprovalEvidence,
    PermissionGrant,
    PolicyEngine,
    PolicyPrincipal,
    PolicyStatus,
    RiskLevel,
    ToolPolicy,
)
from cortexstone.tools.runner import (
    ToolExecutionDenied,
    ToolNotRegisteredError,
    ToolRunner,
)

READ_ACTION = ProposedAction(
    tool_name="notes.search",
    target_ref="notes/personal",
    arguments={"query": "project"},
    purpose="Search personal notes",
)
WRITE_ACTION = ProposedAction(
    tool_name="notes.create",
    target_ref="notes/personal",
    arguments={"title": "Plan", "content": "Draft"},
    purpose="Create a note",
)
PRINCIPAL = PolicyPrincipal(
    principal_id="trusted-user",
    grants=(
        PermissionGrant(
            tool_name="notes.search",
            scope=ActionScope.READ,
            allowed_targets=frozenset({"notes/personal"}),
        ),
        PermissionGrant(
            tool_name="notes.create",
            scope=ActionScope.WRITE,
            allowed_targets=frozenset({"notes/personal"}),
        ),
    ),
)
POLICY_ENGINE = PolicyEngine(
    [
        ToolPolicy(
            tool_name="notes.search",
            scope=ActionScope.READ,
            risk=RiskLevel.LOW,
            allowed_targets=frozenset({"notes/personal"}),
            required_arguments=frozenset({"query"}),
        ),
        ToolPolicy(
            tool_name="notes.create",
            scope=ActionScope.WRITE,
            risk=RiskLevel.LOW,
            allowed_targets=frozenset({"notes/personal"}),
            required_arguments=frozenset({"title", "content"}),
        ),
    ]
)


def run(coroutine):
    return asyncio.run(coroutine)


def test_runner_checks_action_before_calling_executor():
    executed_actions = []

    async def executor(action: ProposedAction):
        executed_actions.append(action)
        return {"result": "verified"}

    runner = ToolRunner(POLICY_ENGINE, {"notes.search": executor})

    result = run(runner.execute(PRINCIPAL, READ_ACTION))

    assert result == {"result": "verified"}
    assert executed_actions == [READ_ACTION]


@pytest.mark.parametrize(
    ("action", "principal"),
    [
        (
            ProposedAction(
                tool_name="notes.unknown",
                target_ref="notes/personal",
                purpose="Unknown tool",
            ),
            PRINCIPAL,
        ),
        (
            READ_ACTION,
            PolicyPrincipal(principal_id="no-grants", grants=()),
        ),
        (
            ProposedAction(
                tool_name="notes.search",
                target_ref="notes/private",
                arguments={"query": "private"},
                purpose="Search disallowed notes",
            ),
            PRINCIPAL,
        ),
    ],
)
def test_runner_never_executes_policy_denied_action(action, principal):
    executed = False

    async def executor(_action: ProposedAction):
        nonlocal executed
        executed = True

    runner = ToolRunner(POLICY_ENGINE, {"notes.search": executor})

    with pytest.raises(ToolExecutionDenied):
        run(runner.execute(principal, action))

    assert not executed


def test_runner_requires_approval_before_write_executor():
    executed = False

    async def executor(_action: ProposedAction):
        nonlocal executed
        executed = True

    runner = ToolRunner(POLICY_ENGINE, {"notes.create": executor})

    with pytest.raises(ToolExecutionDenied) as error:
        run(runner.execute(PRINCIPAL, WRITE_ACTION))

    assert error.value.decision.status == PolicyStatus.REQUIRE_APPROVAL
    assert not executed


def test_runner_resolves_and_validates_approval_immediately_before_execution():
    events = []

    async def resolve_approval(principal: PolicyPrincipal, action: ProposedAction):
        events.append(("approval", principal.principal_id, action.action_id))
        return ApprovalEvidence(
            approved=True,
            action_hash=PolicyEngine.action_hash(action),
            target_ref=action.target_ref,
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )

    async def executor(action: ProposedAction):
        events.append(("execute", action.action_id))
        return "done"

    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.create": executor},
        approval_resolver=resolve_approval,
    )

    result = run(runner.execute(PRINCIPAL, WRITE_ACTION))

    assert result == "done"
    assert events == [
        ("approval", PRINCIPAL.principal_id, WRITE_ACTION.action_id),
        ("execute", WRITE_ACTION.action_id),
    ]


def test_runner_denies_stale_approval_without_executing():
    executed = False

    async def resolve_approval(_principal: PolicyPrincipal, action: ProposedAction):
        return ApprovalEvidence(
            approved=True,
            action_hash=PolicyEngine.action_hash(action),
            target_ref=action.target_ref,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

    async def executor(_action: ProposedAction):
        nonlocal executed
        executed = True

    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.create": executor},
        approval_resolver=resolve_approval,
    )

    with pytest.raises(ToolExecutionDenied):
        run(runner.execute(PRINCIPAL, WRITE_ACTION))

    assert not executed


def test_runner_checks_policy_before_executor_registry():
    runner = ToolRunner(POLICY_ENGINE, {})

    with pytest.raises(ToolExecutionDenied):
        run(
            runner.execute(
                PolicyPrincipal(principal_id="no-grants", grants=()),
                READ_ACTION,
            )
        )

    with pytest.raises(ToolNotRegisteredError):
        run(runner.execute(PRINCIPAL, READ_ACTION))
