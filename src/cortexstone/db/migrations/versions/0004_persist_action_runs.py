"""Persist action execution attempts and lifecycle audit events.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_hash", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("policy_reason", sa.String(length=64), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'awaiting_approval', 'denied', 'running', "
            "'succeeded', 'failed', 'cancelled')",
            name="status_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_action_runs"),
    )
    op.create_index(
        "ix_action_runs_principal_created",
        "action_runs",
        ["principal_id", "created_at"],
    )
    op.create_index("ix_action_runs_action_id", "action_runs", ["action_id"])


def downgrade() -> None:
    op.drop_index("ix_action_runs_action_id", table_name="action_runs")
    op.drop_index("ix_action_runs_principal_created", table_name="action_runs")
    op.drop_table("action_runs")
