"""The only supported boundary for executing proposed tool actions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.security.action_runs import (
    ActionFailureCode,
    ActionRunRecorder,
    ActionRunStatus,
)
from cortexstone.security.policy import (
    ApprovalEvidence,
    PolicyDecision,
    PolicyEngine,
    PolicyPrincipal,
    PolicyStatus,
)

ToolExecutor = Callable[[ProposedAction], Awaitable[Any]]
ApprovalResolver = Callable[
    [PolicyPrincipal, ProposedAction],
    Awaitable[ApprovalEvidence | None],
]


class ToolExecutionError(Exception):
    """Base error for blocked tool execution."""


class ToolExecutionDenied(ToolExecutionError):
    """Raised when policy does not authorize the proposed action."""

    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        super().__init__(f"Tool execution blocked by policy: {decision.reason.value}")


class ToolNotRegisteredError(ToolExecutionError):
    """Raised when an allowed tool has no registered executor."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"No executor is registered for tool: {tool_name}")


class ToolRunner:
    """Evaluate each action immediately before dispatching its registered executor."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        executors: Mapping[str, ToolExecutor],
        *,
        run_recorder: ActionRunRecorder,
        approval_resolver: ApprovalResolver | None = None,
    ) -> None:
        self._policy_engine = policy_engine
        self._executors = dict(executors)
        self._run_recorder = run_recorder
        self._approval_resolver = approval_resolver

    async def execute(self, principal: PolicyPrincipal, action: ProposedAction) -> Any:
        """Persist, authorize, and execute one action with durable lifecycle state."""
        run_id = await self._run_recorder.create_attempt(principal.principal_id, action)
        approval = None
        if self._approval_resolver is not None:
            try:
                approval = await self._approval_resolver(principal, action)
            except asyncio.CancelledError:
                await self._run_recorder.transition(run_id, ActionRunStatus.CANCELLED)
                raise
            except Exception:
                await self._run_recorder.transition(
                    run_id,
                    ActionRunStatus.FAILED,
                    failure_code=ActionFailureCode.APPROVAL_RESOLUTION_FAILED,
                )
                raise

        try:
            decision = await self._policy_engine.evaluate_async(
                principal, action, approval=approval
            )
        except asyncio.CancelledError:
            await self._run_recorder.transition(run_id, ActionRunStatus.CANCELLED)
            raise
        except Exception:
            await self._run_recorder.transition(
                run_id,
                ActionRunStatus.FAILED,
                failure_code=ActionFailureCode.POLICY_EVALUATION_FAILED,
            )
            raise
        if decision.status != PolicyStatus.ALLOW:
            run_status = (
                ActionRunStatus.AWAITING_APPROVAL
                if decision.status == PolicyStatus.REQUIRE_APPROVAL
                else ActionRunStatus.DENIED
            )
            await self._run_recorder.transition(
                run_id,
                run_status,
                policy_reason=decision.reason,
            )
            raise ToolExecutionDenied(decision)

        executor = self._executors.get(action.tool_name)
        if executor is None:
            await self._run_recorder.transition(
                run_id,
                ActionRunStatus.FAILED,
                failure_code=ActionFailureCode.EXECUTOR_UNAVAILABLE,
            )
            raise ToolNotRegisteredError(action.tool_name)

        await self._run_recorder.transition(
            run_id,
            ActionRunStatus.RUNNING,
            approval_accepted=approval is not None,
        )
        try:
            result = await executor(action)
        except asyncio.CancelledError:
            await self._run_recorder.transition(run_id, ActionRunStatus.CANCELLED)
            raise
        except Exception:
            await self._run_recorder.transition(
                run_id,
                ActionRunStatus.FAILED,
                failure_code=ActionFailureCode.EXECUTOR_FAILED,
            )
            raise

        await self._run_recorder.transition(run_id, ActionRunStatus.SUCCEEDED)
        return result
