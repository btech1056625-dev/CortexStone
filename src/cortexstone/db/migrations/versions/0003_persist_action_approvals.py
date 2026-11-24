"""Persist action approval requests and decisions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("action_hash", sa.String(length=64), nullable=False),
        sa.Column("target_ref", sa.String(length=512), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("action_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'revoked')",
            name="status_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
    )
    op.create_index(
        "ix_approvals_owner_created",
        "approvals",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_approvals_action_lookup",
        "approvals",
        ["owner_id", "action_hash", "target_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_action_lookup", table_name="approvals")
    op.drop_index("ix_approvals_owner_created", table_name="approvals")
    op.drop_table("approvals")
