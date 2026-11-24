"""Add persistent permission grants and security audit history.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "permission_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("allowed_targets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("scope IN ('read', 'write')", name="scope_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_permission_grants"),
    )
    op.create_index(
        "ix_permission_grants_principal_active",
        "permission_grants",
        ["principal_id", "revoked_at"],
    )
    op.create_table(
        "security_audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_security_audit_events"),
    )
    op.create_index(
        "ix_security_audit_events_subject_time",
        "security_audit_events",
        ["subject_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_audit_events_subject_time",
        table_name="security_audit_events",
    )
    op.drop_table("security_audit_events")
    op.drop_index(
        "ix_permission_grants_principal_active",
        table_name="permission_grants",
    )
    op.drop_table("permission_grants")
