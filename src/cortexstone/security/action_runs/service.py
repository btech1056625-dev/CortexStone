"""Persist action execution lifecycle and redacted audit events."""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.db.models.action_runs import ActionRunModel
from cortexstone.db.models.permissions import SecurityAuditEventModel
from cortexstone.security.policy import PolicyEngine, PolicyReason


class ActionRunStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionFailureCode(StrEnum):
    APPROVAL_RESOLUTION_FAILED = "approval_resolution_failed"
    POLICY_EVALUATION_FAILED = "policy_evaluation_failed"
    EXECUTOR_UNAVAILABLE = "executor_unavailable"
    EXECUTOR_FAILED = "executor_failed"


class ActionRunRecorder(Protocol):
    """Persistence boundary used by ToolRunner for every action attempt."""

    async def create_attempt(self, principal_id: str, action: ProposedAction) -> UUID:
        """Persist the attempt before policy evaluation or executor dispatch."""
        ...

    async def transition(
        self,
        run_id: UUID,
        status: ActionRunStatus,
        *,
        policy_reason: PolicyReason | None = None,
        failure_code: ActionFailureCode | None = None,
        approval_accepted: bool = False,
    ) -> None:
        """Persist a lifecycle transition and corresponding redacted audit events."""
        ...


class ActionRunStateError(RuntimeError):
    """Raised when an execution attempt has an invalid lifecycle transition."""


class SqlAlchemyActionRunService:
    """Store action attempts and append-only lifecycle audit metadata."""

    _TRANSITIONS: Mapping[ActionRunStatus, frozenset[ActionRunStatus]] = {
        ActionRunStatus.PENDING: frozenset(
            {
                ActionRunStatus.AWAITING_APPROVAL,
                ActionRunStatus.DENIED,
                ActionRunStatus.RUNNING,
                ActionRunStatus.FAILED,
                ActionRunStatus.CANCELLED,
            }
        ),
        ActionRunStatus.RUNNING: frozenset(
            {
                ActionRunStatus.SUCCEEDED,
                ActionRunStatus.FAILED,
                ActionRunStatus.CANCELLED,
            }
        ),
    }

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_attempt(self, principal_id: str, action: ProposedAction) -> UUID:
        try:
            action_hash = PolicyEngine.action_hash(action)
        except (TypeError, ValueError):
            action_hash = None

        async with self._session_factory() as session, session.begin():
            run = ActionRunModel(
                principal_id=principal_id,
                action_id=action.action_id,
                action_hash=action_hash,
                tool_name=action.tool_name,
                status=ActionRunStatus.PENDING.value,
            )
            session.add(run)
            await session.flush()
            self._add_audit_event(
                session,
                event_type="action.attempted",
                principal_id=principal_id,
                run=run,
                status=ActionRunStatus.PENDING,
            )
            await session.flush()
            return run.id

    async def transition(
        self,
        run_id: UUID,
        status: ActionRunStatus,
        *,
        policy_reason: PolicyReason | None = None,
        failure_code: ActionFailureCode | None = None,
        approval_accepted: bool = False,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            run = await session.scalar(
                select(ActionRunModel).where(ActionRunModel.id == run_id).with_for_update()
            )
            if run is None:
                raise ActionRunStateError("Action run does not exist.")

            current_status = ActionRunStatus(run.status)
            if status not in self._TRANSITIONS.get(current_status, frozenset()):
                raise ActionRunStateError(
                    f"Invalid action run transition: {current_status.value} -> {status.value}."
                )

            now = datetime.now(UTC)
            run.status = status.value
            run.policy_reason = policy_reason.value if policy_reason is not None else None
            run.failure_code = failure_code.value if failure_code is not None else None
            if status == ActionRunStatus.RUNNING:
                run.started_at = now
            if status in {
                ActionRunStatus.DENIED,
                ActionRunStatus.SUCCEEDED,
                ActionRunStatus.FAILED,
                ActionRunStatus.CANCELLED,
            }:
                run.finished_at = now

            if approval_accepted:
                self._add_audit_event(
                    session,
                    event_type="action.approval_accepted",
                    principal_id=run.principal_id,
                    run=run,
                    status=status,
                )
            self._add_audit_event(
                session,
                event_type=f"action.{status.value}",
                principal_id=run.principal_id,
                run=run,
                status=status,
                policy_reason=policy_reason,
                failure_code=failure_code,
            )

    @staticmethod
    def _add_audit_event(
        session: AsyncSession,
        *,
        event_type: str,
        principal_id: str,
        run: ActionRunModel,
        status: ActionRunStatus,
        policy_reason: PolicyReason | None = None,
        failure_code: ActionFailureCode | None = None,
    ) -> None:
        details: dict[str, str] = {
            "run_id": str(run.id),
            "action_id": str(run.action_id),
            "tool_name": run.tool_name,
            "status": status.value,
        }
        if policy_reason is not None:
            details["policy_reason"] = policy_reason.value
        if failure_code is not None:
            details["failure_code"] = failure_code.value
        session.add(
            SecurityAuditEventModel(
                event_type=event_type,
                actor_id=principal_id,
                subject_id=principal_id,
                resource_id=run.id,
                details=details,
            )
        )
