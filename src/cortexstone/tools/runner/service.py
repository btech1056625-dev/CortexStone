"""The only supported boundary for executing proposed tool actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from cortexstone.agent.schemas.actions import ProposedAction
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
        approval_resolver: ApprovalResolver | None = None,
    ) -> None:
        self._policy_engine = policy_engine
        self._executors = dict(executors)
        self._approval_resolver = approval_resolver

    async def execute(self, principal: PolicyPrincipal, action: ProposedAction) -> Any:
        """Freshly validate an action and only then call its registered executor."""
        approval = None
        if self._approval_resolver is not None:
            approval = await self._approval_resolver(principal, action)

        decision = self._policy_engine.evaluate(principal, action, approval=approval)
        if decision.status != PolicyStatus.ALLOW:
            raise ToolExecutionDenied(decision)

        executor = self._executors.get(action.tool_name)
        if executor is None:
            raise ToolNotRegisteredError(action.tool_name)

        return await executor(action)
