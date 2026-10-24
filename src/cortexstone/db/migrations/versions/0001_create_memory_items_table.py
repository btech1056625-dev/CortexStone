"""Create memory_items table with pgvector support and HNSW index.

Revision ID: 0001
Revises:
Create Date: 2026-10-24 14:00:00.000000

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure the pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "memory_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "sensitivity",
            sa.String(length=20),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        sa.Column(
            "approved",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "kind IN ('fact', 'episode', 'skill')",
            name="kind_valid",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "sensitivity IN ('normal', 'sensitive', 'internal')",
            name="sensitivity_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_items"),
    )

    op.create_index(
        "ix_memory_items_owner_id",
        "memory_items",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_items_deleted_at",
        "memory_items",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_memory_items_owner_kind_active",
        "memory_items",
        ["owner_id", "kind"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_memory_items_owner_occurred_at",
        "memory_items",
        ["owner_id", "occurred_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_memory_items_embedding_hnsw",
        "memory_items",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_where=sa.text("deleted_at IS NULL AND embedding IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_items_embedding_hnsw",
        table_name="memory_items",
        postgresql_where=sa.text("deleted_at IS NULL AND embedding IS NOT NULL"),
    )
    op.drop_index(
        "ix_memory_items_owner_occurred_at",
        table_name="memory_items",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_memory_items_owner_kind_active",
        table_name="memory_items",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_memory_items_deleted_at", table_name="memory_items")
    op.drop_index("ix_memory_items_owner_id", table_name="memory_items")
    op.drop_table("memory_items")
