import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.security.action_runs import ActionRunStatus
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


class InMemoryActionRunRecorder:
    def __init__(self) -> None:
        self.runs: dict[UUID, ActionRunStatus] = {}
        self.transitions: list[tuple[UUID, ActionRunStatus]] = []

    async def create_attempt(self, _principal_id: str, _action: ProposedAction) -> UUID:
        run_id = uuid4()
        self.runs[run_id] = ActionRunStatus.PENDING
        return run_id

    async def transition(
        self,
        run_id: UUID,
        status: ActionRunStatus,
        *,
        policy_reason=None,
        failure_code=None,
        approval_accepted: bool = False,
    ) -> None:
        self.runs[run_id] = status
        self.transitions.append((run_id, status))


def test_runner_checks_action_before_calling_executor():
    executed_actions = []
    recorder = InMemoryActionRunRecorder()

    async def executor(action: ProposedAction):
        executed_actions.append(action)
        return {"result": "verified"}

    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.search": executor},
        run_recorder=recorder,
    )

    result = run(runner.execute(PRINCIPAL, READ_ACTION))

    assert result == {"result": "verified"}
    assert executed_actions == [READ_ACTION]
    assert list(recorder.runs.values()) == [ActionRunStatus.SUCCEEDED]
    assert [status for _, status in recorder.transitions] == [
        ActionRunStatus.RUNNING,
        ActionRunStatus.SUCCEEDED,
    ]


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
    recorder = InMemoryActionRunRecorder()

    async def executor(_action: ProposedAction):
        nonlocal executed
        executed = True

    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.search": executor},
        run_recorder=recorder,
    )

    with pytest.raises(ToolExecutionDenied):
        run(runner.execute(principal, action))

    assert not executed
    expected_status = (
        ActionRunStatus.AWAITING_APPROVAL
        if action.tool_name == "notes.create"
        else ActionRunStatus.DENIED
    )
    assert list(recorder.runs.values()) == [expected_status]


def test_runner_requires_approval_before_write_executor():
    executed = False
    recorder = InMemoryActionRunRecorder()

    async def executor(_action: ProposedAction):
        nonlocal executed
        executed = True

    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.create": executor},
        run_recorder=recorder,
    )

    with pytest.raises(ToolExecutionDenied) as error:
        run(runner.execute(PRINCIPAL, WRITE_ACTION))

    assert error.value.decision.status == PolicyStatus.REQUIRE_APPROVAL
    assert not executed
    assert list(recorder.runs.values()) == [ActionRunStatus.AWAITING_APPROVAL]


def test_runner_resolves_and_validates_approval_immediately_before_execution():
    events = []
    recorder = InMemoryActionRunRecorder()

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
        run_recorder=recorder,
        approval_resolver=resolve_approval,
    )

    result = run(runner.execute(PRINCIPAL, WRITE_ACTION))

    assert result == "done"
    assert events == [
        ("approval", PRINCIPAL.principal_id, WRITE_ACTION.action_id),
        ("execute", WRITE_ACTION.action_id),
    ]
    assert list(recorder.runs.values()) == [ActionRunStatus.SUCCEEDED]


def test_runner_denies_stale_approval_without_executing():
    executed = False
    recorder = InMemoryActionRunRecorder()

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
        run_recorder=recorder,
        approval_resolver=resolve_approval,
    )

    with pytest.raises(ToolExecutionDenied):
        run(runner.execute(PRINCIPAL, WRITE_ACTION))

    assert not executed
    assert list(recorder.runs.values()) == [ActionRunStatus.AWAITING_APPROVAL]


def test_runner_checks_policy_before_executor_registry():
    recorder = InMemoryActionRunRecorder()
    runner = ToolRunner(POLICY_ENGINE, {}, run_recorder=recorder)

    with pytest.raises(ToolExecutionDenied):
        run(
            runner.execute(
                PolicyPrincipal(principal_id="no-grants", grants=()),
                READ_ACTION,
            )
        )

    with pytest.raises(ToolNotRegisteredError):
        run(runner.execute(PRINCIPAL, READ_ACTION))
    assert list(recorder.runs.values()) == [
        ActionRunStatus.DENIED,
        ActionRunStatus.FAILED,
    ]


@pytest.mark.parametrize("tool_name", ["python.exec", "shell.exec"])
def test_runner_denies_unregistered_code_execution_tools(tool_name):
    executed_actions = []
    recorder = InMemoryActionRunRecorder()

    async def notes_executor(action: ProposedAction):
        executed_actions.append(action)

    action = ProposedAction(
        tool_name=tool_name,
        target_ref="local",
        arguments={"code": "not executed"},
        purpose="Attempt arbitrary code execution",
    )
    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.search": notes_executor},
        run_recorder=recorder,
    )

    with pytest.raises(ToolExecutionDenied):
        run(runner.execute(PRINCIPAL, action))

    assert executed_actions == []
    assert list(recorder.runs.values()) == [ActionRunStatus.DENIED]


def test_runner_rechecks_persisted_permissions_before_executor():
    class RevokingPermissionService:
        def __init__(self) -> None:
            self.calls = 0
            self.revoked = False

        async def get_grants(self, principal_id: str):
            self.calls += 1
            return () if self.revoked else PRINCIPAL.grants

    service = RevokingPermissionService()
    recorder = InMemoryActionRunRecorder()
    engine = PolicyEngine(
        [
            ToolPolicy(
                tool_name="notes.search",
                scope=ActionScope.READ,
                risk=RiskLevel.LOW,
                allowed_targets=frozenset({"notes/personal"}),
                required_arguments=frozenset({"query"}),
            )
        ],
        async_permission_service=service,
    )
    executed = False

    async def executor(_action: ProposedAction):
        nonlocal executed
        executed = True

    runner = ToolRunner(engine, {"notes.search": executor}, run_recorder=recorder)

    async def preflight_then_revoke() -> None:
        assert (await engine.evaluate_async(PRINCIPAL, READ_ACTION)).status == PolicyStatus.ALLOW
        service.revoked = True
        with pytest.raises(ToolExecutionDenied):
            await runner.execute(PRINCIPAL, READ_ACTION)

    run(preflight_then_revoke())

    assert service.calls == 2
    assert not executed
    assert list(recorder.runs.values()) == [ActionRunStatus.DENIED]


def test_runner_persists_executor_failures_without_exposing_exception_text():
    recorder = InMemoryActionRunRecorder()

    async def executor(_action: ProposedAction):
        raise RuntimeError("sensitive provider response")

    runner = ToolRunner(
        POLICY_ENGINE,
        {"notes.search": executor},
        run_recorder=recorder,
    )

    with pytest.raises(RuntimeError, match="sensitive provider response"):
        run(runner.execute(PRINCIPAL, READ_ACTION))

    assert list(recorder.runs.values()) == [ActionRunStatus.FAILED]
    assert [status for _, status in recorder.transitions] == [
        ActionRunStatus.RUNNING,
        ActionRunStatus.FAILED,
    ]
