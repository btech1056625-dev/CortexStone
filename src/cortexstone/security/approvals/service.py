"""Database-backed action approval requests and decisions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.db.models.approvals import ApprovalModel
from cortexstone.db.models.permissions import SecurityAuditEventModel
from cortexstone.security.policy import ApprovalEvidence, PolicyEngine, PolicyPrincipal

APPROVAL_TTL = timedelta(minutes=15)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApprovalConflictError(Exception):
    """Raised when an approval is already decided or expired."""


@dataclass(frozen=True)
class ApprovalRecord:
    """Approval data safe to return to its owning principal."""

    id: UUID
    owner_id: str
    action: ProposedAction
    action_hash: str
    status: ApprovalStatus
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None


class SqlAlchemyApprovalService:
    """Persist approvals and expose an uncached pre-execution approval resolver."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        owner_id: str,
        action: ProposedAction,
    ) -> ApprovalRecord:
        now = datetime.now(UTC)
        action_hash = PolicyEngine.action_hash(action)
        async with self._session_factory() as session, session.begin():
            approval = ApprovalModel(
                owner_id=owner_id,
                action_hash=action_hash,
                target_ref=action.target_ref,
                tool_name=action.tool_name,
                action_data=action.model_dump(mode="json"),
                status=ApprovalStatus.PENDING.value,
                expires_at=now + APPROVAL_TTL,
            )
            session.add(approval)
            await session.flush()
            session.add(
                self._audit_event(
                    event_type="approval.requested",
                    actor_id=owner_id,
                    subject_id=owner_id,
                    resource_id=approval.id,
                    details={
                        "tool_name": action.tool_name,
                        "target_ref": action.target_ref,
                        "action_hash": action_hash,
                    },
                )
            )
            return self._record(approval)

    async def list_for_owner(self, owner_id: str) -> tuple[ApprovalRecord, ...]:
        async with self._session_factory() as session, session.begin():
            result = await session.scalars(
                select(ApprovalModel)
                .where(ApprovalModel.owner_id == owner_id)
                .order_by(ApprovalModel.created_at.desc(), ApprovalModel.id)
                .with_for_update()
            )
            approvals = tuple(result)
            now = datetime.now(UTC)
            for approval in approvals:
                self._expire_pending(session, approval, now)
            return tuple(self._record(approval) for approval in approvals)

    async def decide(
        self,
        approval_id: UUID,
        *,
        owner_id: str,
        decision: ApprovalStatus,
    ) -> ApprovalRecord | None:
        if decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("Approval decision must be approved or rejected.")

        expired = False
        record: ApprovalRecord | None = None
        async with self._session_factory() as session, session.begin():
            approval = await session.scalar(
                select(ApprovalModel)
                .where(
                    ApprovalModel.id == approval_id,
                    ApprovalModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if approval is None:
                return None
            if approval.status != ApprovalStatus.PENDING.value:
                raise ApprovalConflictError("Approval request is no longer pending.")

            now = datetime.now(UTC)
            if self._expire_pending(session, approval, now):
                expired = True
            else:
                approval.status = decision.value
                approval.decided_at = now
                approval.decided_by = owner_id
                session.add(
                    self._audit_event(
                        event_type=f"approval.{approval.status}",
                        actor_id=owner_id,
                        subject_id=owner_id,
                        resource_id=approval.id,
                        details={
                            "tool_name": approval.tool_name,
                            "target_ref": approval.target_ref,
                            "action_hash": approval.action_hash,
                        },
                    )
                )
            await session.flush()
            record = self._record(approval)

        if expired:
            raise ApprovalConflictError("Approval request has expired.")
        return record

    async def revoke(self, approval_id: UUID, *, owner_id: str) -> ApprovalRecord | None:
        async with self._session_factory() as session, session.begin():
            approval = await session.scalar(
                select(ApprovalModel)
                .where(
                    ApprovalModel.id == approval_id,
                    ApprovalModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if approval is None:
                return None
            if approval.status not in {
                ApprovalStatus.PENDING.value,
                ApprovalStatus.APPROVED.value,
            }:
                raise ApprovalConflictError("Approval request cannot be revoked.")

            now = datetime.now(UTC)
            approval.status = ApprovalStatus.REVOKED.value
            approval.decided_at = now
            approval.decided_by = owner_id
            session.add(
                self._audit_event(
                    event_type="approval.revoked",
                    actor_id=owner_id,
                    subject_id=owner_id,
                    resource_id=approval.id,
                    details={
                        "tool_name": approval.tool_name,
                        "target_ref": approval.target_ref,
                        "action_hash": approval.action_hash,
                    },
                )
            )
            await session.flush()
            return self._record(approval)

    async def resolve_for_action(
        self,
        principal: PolicyPrincipal,
        action: ProposedAction,
    ) -> ApprovalEvidence | None:
        """Resolve current persisted evidence for ToolRunner immediately before dispatch."""
        action_hash = PolicyEngine.action_hash(action)
        async with self._session_factory() as session, session.begin():
            approval = await session.scalar(
                select(ApprovalModel)
                .where(
                    ApprovalModel.owner_id == principal.principal_id,
                    ApprovalModel.action_hash == action_hash,
                    ApprovalModel.target_ref == action.target_ref,
                )
                .order_by(ApprovalModel.created_at.desc(), ApprovalModel.id)
                .limit(1)
                .with_for_update()
            )
            if approval is None:
                return None
            expired = self._expire_pending(session, approval, datetime.now(UTC))
            if approval.status == ApprovalStatus.PENDING.value:
                return None
            if expired:
                await session.flush()
            return ApprovalEvidence(
                approved=approval.status
                in {ApprovalStatus.APPROVED.value, ApprovalStatus.EXPIRED.value},
                action_hash=approval.action_hash,
                target_ref=approval.target_ref,
                expires_at=approval.expires_at,
                principal_id=approval.owner_id,
                revoked=approval.status == ApprovalStatus.REVOKED.value,
            )

    @classmethod
    def _expire_pending(
        cls,
        session: AsyncSession,
        approval: ApprovalModel,
        now: datetime,
    ) -> bool:
        if approval.status != ApprovalStatus.PENDING.value or approval.expires_at > now:
            return False
        approval.status = ApprovalStatus.EXPIRED.value
        approval.decided_at = now
        approval.decided_by = approval.owner_id
        session.add(
            cls._audit_event(
                event_type="approval.expired",
                actor_id="system",
                subject_id=approval.owner_id,
                resource_id=approval.id,
                details={
                    "tool_name": approval.tool_name,
                    "target_ref": approval.target_ref,
                    "action_hash": approval.action_hash,
                },
            )
        )
        return True

    @staticmethod
    def _record(approval: ApprovalModel) -> ApprovalRecord:
        approval_status = ApprovalStatus(approval.status)
        if approval_status == ApprovalStatus.PENDING and approval.expires_at <= datetime.now(UTC):
            approval_status = ApprovalStatus.EXPIRED
        return ApprovalRecord(
            id=approval.id,
            owner_id=approval.owner_id,
            action=ProposedAction.model_validate(approval.action_data),
            action_hash=approval.action_hash,
            status=approval_status,
            expires_at=approval.expires_at,
            created_at=approval.created_at,
            decided_at=approval.decided_at,
            decided_by=approval.decided_by,
        )

    @staticmethod
    def _audit_event(
        *,
        event_type: str,
        actor_id: str,
        subject_id: str,
        resource_id: UUID,
        details: dict[str, Any],
    ) -> SecurityAuditEventModel:
        return SecurityAuditEventModel(
            event_type=event_type,
            actor_id=actor_id,
            subject_id=subject_id,
            resource_id=resource_id,
            details=details,
        )
