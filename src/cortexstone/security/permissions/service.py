"""Database-backed permission storage with atomic audit logging."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cortexstone.db.base import utc_now
from cortexstone.db.models.permissions import PermissionGrantModel, SecurityAuditEventModel
from cortexstone.security.policy import ActionScope, PermissionGrant


@dataclass(frozen=True)
class PermissionGrantRecord:
    """Permission grant data safe to return from the management API."""

    id: UUID
    principal_id: str
    tool_name: str
    scope: ActionScope
    allowed_targets: tuple[str, ...]
    granted_by: str
    created_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None


class SqlAlchemyPermissionService:
    """Resolve current grants without caching and persist audited changes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_grants(self, principal_id: str) -> tuple[PermissionGrant, ...]:
        """Read active grants on every call so revocation takes effect immediately."""
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PermissionGrantModel).where(
                    PermissionGrantModel.principal_id == principal_id,
                    PermissionGrantModel.revoked_at.is_(None),
                )
            )
            return tuple(
                PermissionGrant(
                    tool_name=grant.tool_name,
                    scope=ActionScope(grant.scope),
                    allowed_targets=frozenset(grant.allowed_targets),
                )
                for grant in result
            )

    async def list_grants(self, principal_id: str) -> tuple[PermissionGrantRecord, ...]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PermissionGrantModel)
                .where(PermissionGrantModel.principal_id == principal_id)
                .order_by(PermissionGrantModel.created_at.desc(), PermissionGrantModel.id)
            )
            return tuple(self._record(grant) for grant in result)

    async def grant(
        self,
        *,
        principal_id: str,
        tool_name: str,
        scope: ActionScope,
        allowed_targets: tuple[str, ...],
        actor_id: str,
    ) -> tuple[PermissionGrantRecord, bool]:
        """Create a grant and audit event atomically; identical active grants are idempotent."""
        targets = tuple(sorted(set(allowed_targets)))
        async with self._session_factory() as session, session.begin():
            active_grants = await session.scalars(
                select(PermissionGrantModel).where(
                    PermissionGrantModel.principal_id == principal_id,
                    PermissionGrantModel.tool_name == tool_name,
                    PermissionGrantModel.scope == scope.value,
                    PermissionGrantModel.revoked_at.is_(None),
                )
            )
            for existing in active_grants:
                if tuple(sorted(existing.allowed_targets)) == targets:
                    return self._record(existing), False

            grant = PermissionGrantModel(
                principal_id=principal_id,
                tool_name=tool_name,
                scope=scope.value,
                allowed_targets=list(targets),
                granted_by=actor_id,
            )
            session.add(grant)
            await session.flush()
            session.add(
                self._audit_event(
                    event_type="permission.granted",
                    actor_id=actor_id,
                    subject_id=principal_id,
                    resource_id=grant.id,
                    details={
                        "tool_name": tool_name,
                        "scope": scope.value,
                        "allowed_targets": list(targets),
                    },
                )
            )
            return self._record(grant), True

    async def revoke(
        self,
        grant_id: UUID,
        *,
        actor_id: str,
    ) -> PermissionGrantRecord | None:
        """Revoke one active grant and atomically append its audit event."""
        async with self._session_factory() as session, session.begin():
            grant = await session.scalar(
                select(PermissionGrantModel)
                .where(
                    PermissionGrantModel.id == grant_id,
                    PermissionGrantModel.revoked_at.is_(None),
                )
                .with_for_update()
            )
            if grant is None:
                return None

            grant.revoked_at = utc_now()
            grant.revoked_by = actor_id
            session.add(
                self._audit_event(
                    event_type="permission.revoked",
                    actor_id=actor_id,
                    subject_id=grant.principal_id,
                    resource_id=grant.id,
                    details={
                        "tool_name": grant.tool_name,
                        "scope": grant.scope,
                        "allowed_targets": list(grant.allowed_targets),
                    },
                )
            )
            await session.flush()
            return self._record(grant)

    async def revoke_principal(self, principal_id: str, *, actor_id: str) -> int:
        """Revoke every active grant for an offboarded or role-changed principal."""
        async with self._session_factory() as session, session.begin():
            result = await session.scalars(
                select(PermissionGrantModel)
                .where(
                    PermissionGrantModel.principal_id == principal_id,
                    PermissionGrantModel.revoked_at.is_(None),
                )
                .with_for_update()
            )
            grants = tuple(result)
            revoked_at = utc_now()
            for grant in grants:
                grant.revoked_at = revoked_at
                grant.revoked_by = actor_id
                session.add(
                    self._audit_event(
                        event_type="permission.revoked",
                        actor_id=actor_id,
                        subject_id=principal_id,
                        resource_id=grant.id,
                        details={
                            "tool_name": grant.tool_name,
                            "scope": grant.scope,
                            "allowed_targets": list(grant.allowed_targets),
                            "reason": "principal_access_revoked",
                        },
                    )
                )
            return len(grants)

    @staticmethod
    def _record(grant: PermissionGrantModel) -> PermissionGrantRecord:
        return PermissionGrantRecord(
            id=grant.id,
            principal_id=grant.principal_id,
            tool_name=grant.tool_name,
            scope=ActionScope(grant.scope),
            allowed_targets=tuple(grant.allowed_targets),
            granted_by=grant.granted_by,
            created_at=grant.created_at,
            revoked_at=grant.revoked_at,
            revoked_by=grant.revoked_by,
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
