"""Persistence models for permission grants and security audit history."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from cortexstone.db.base import Base, TimestampMixin
from cortexstone.security.redaction import redact_secrets, redact_value


class PermissionGrantModel(Base, TimestampMixin):
    """An auditable, revocable grant for one principal, tool, scope, and target set."""

    __tablename__ = "permission_grants"
    __table_args__ = (
        CheckConstraint("scope IN ('read', 'write')", name="scope_valid"),
        Index("ix_permission_grants_principal_active", "principal_id", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    allowed_targets: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(Text, nullable=True)


class SecurityAuditEventModel(Base):
    """Append-only, content-redacted security and action lifecycle audit metadata."""

    __tablename__ = "security_audit_events"
    __table_args__ = (Index("ix_security_audit_events_subject_time", "subject_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    @validates("event_type", "actor_id", "subject_id")
    def redact_text(self, _key: str, value: str) -> str:
        return redact_secrets(value)

    @validates("details")
    def redact_details(self, _key: str, value: dict[str, Any]) -> dict[str, Any]:
        return redact_value(value)
