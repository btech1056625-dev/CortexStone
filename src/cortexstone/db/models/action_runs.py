"""Persistence model for action execution attempts and lifecycle state."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cortexstone.db.base import Base


class ActionRunModel(Base):
    """A durable execution attempt without raw action or executor payloads."""

    __tablename__ = "action_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'awaiting_approval', 'denied', 'running', "
            "'succeeded', 'failed', 'cancelled')",
            name="status_valid",
        ),
        Index("ix_action_runs_principal_created", "principal_id", "created_at"),
        Index("ix_action_runs_action_id", "action_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    action_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    policy_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
