"""SQLAlchemy declarative model for CortexStone memory items.

Maps to the documented `memory_items` table in PostgreSQL.
Preserves owner-scoped isolation, memory kind constraints,
provenance, confidence bounds, audit timestamps, and soft deletion.

NOTE ON VECTOR EMBEDDING COLUMN:
The team has NOT yet finalized the embedding model or vector dimension integer.
Therefore, this model isolates the embedding field representation so it does not
freeze a premature dimension integer (e.g., 384 vs 768 vs 1536) in schema migrations.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cortexstone.db.base import Base, TimestampMixin
from cortexstone.memory.embeddings.config import BGE_SMALL_DIMENSION

# Try to import Vector from pgvector.sqlalchemy if installed in the environment.
# If pgvector is not installed, we fallback to a Text placeholder so the ORM model
# can still be inspected, loaded, and tested without failing imports.
try:
    from pgvector.sqlalchemy import Vector  # type: ignore
    from sqlalchemy.ext.compiler import compiles

    PGVECTOR_AVAILABLE = True

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):  # noqa: ARG001
        """Compile pgvector Vector type as TEXT when running on SQLite dialect."""
        return "TEXT"

except ImportError:
    Vector = None  # type: ignore
    PGVECTOR_AVAILABLE = False


class MemoryItemModel(Base, TimestampMixin):
    """SQLAlchemy 2.x persistence model for user-scoped memory items."""

    __tablename__ = "memory_items"

    __table_args__ = (
        CheckConstraint(
            "kind IN ('fact', 'episode', 'skill')",
            name="kind_valid",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="confidence_range",
        ),
        CheckConstraint(
            "sensitivity IN ('normal', 'sensitive', 'internal')",
            name="sensitivity_valid",
        ),
        # Partial index for fast, owner-scoped active retrieval
        Index(
            "ix_memory_items_owner_kind_active",
            "owner_id",
            "kind",
            postgresql_where="deleted_at IS NULL",
        ),
        # Temporal index for timeline and recency queries
        Index(
            "ix_memory_items_owner_occurred_at",
            "owner_id",
            "occurred_at",
            postgresql_where="deleted_at IS NULL",
        ),
        # HNSW vector index using cosine distance (vector_cosine_ops) for BGE embeddings
        Index(
            "ix_memory_items_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where="deleted_at IS NULL AND embedding IS NOT NULL",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Embedding column representation:
    # Uses pgvector Vector(384) matching BAAI/bge-small-en-v1.5 when pgvector is installed,
    # with clean Text fallback for environments where pgvector is absent.
    embedding: Mapped[Any | None] = mapped_column(
        Vector(BGE_SMALL_DIMENSION) if PGVECTOR_AVAILABLE else Text,
        nullable=True,
    )

    source_type: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    source_ref: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    sensitivity: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
    )
    approved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )
