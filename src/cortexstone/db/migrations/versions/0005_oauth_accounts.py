"""Persist provider identities, encrypted OAuth credentials, and transient OAuth state.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_identities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
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
        sa.CheckConstraint("provider IN ('google', 'github')", name="provider_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_identities"),
        sa.UniqueConstraint("provider", "provider_subject", name="provider_subject_unique"),
    )
    op.create_index("ix_oauth_identities_principal", "oauth_identities", ["principal_id"])

    op.create_table(
        "oauth_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.CheckConstraint("provider IN ('google', 'github')", name="provider_valid"),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_credentials"),
        sa.UniqueConstraint("principal_id", "provider", name="principal_provider_unique"),
        sa.UniqueConstraint("provider", "provider_subject", name="provider_subject_unique"),
    )
    op.create_index("ix_oauth_credentials_expiry", "oauth_credentials", ["expires_at"])

    op.create_table(
        "oauth_flows",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=True),
        sa.Column("return_origin", sa.Text(), nullable=False),
        sa.Column("encrypted_code_verifier", sa.Text(), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("provider IN ('google', 'github')", name="provider_valid"),
        sa.CheckConstraint("mode IN ('login', 'connect')", name="mode_valid"),
        sa.PrimaryKeyConstraint("state_hash", name="pk_oauth_flows"),
    )
    op.create_index("ix_oauth_flows_expiry", "oauth_flows", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_oauth_flows_expiry", table_name="oauth_flows")
    op.drop_table("oauth_flows")
    op.drop_index("ix_oauth_credentials_expiry", table_name="oauth_credentials")
    op.drop_table("oauth_credentials")
    op.drop_index("ix_oauth_identities_principal", table_name="oauth_identities")
    op.drop_table("oauth_identities")
