"""Unit tests for Memory domain schemas, SQLAlchemy models, and Embedding interface."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryKind,
    SensitivityLevel,
    utc_now,
)

# -----------------------------------------------------------------------------
# 1. Domain Schema Tests (MemoryKind, SensitivityLevel, Provenance, Validation)
# -----------------------------------------------------------------------------


def test_memory_kind_enums():
    """Verify supported memory kinds."""
    assert MemoryKind.FACT == "fact"
    assert MemoryKind.EPISODE == "episode"
    assert MemoryKind.SKILL == "skill"

    with pytest.raises(ValueError):
        MemoryItemCreate(kind="invalid_kind", content="test")  # type: ignore


def test_sensitivity_level_enums():
    """Verify sensitivity levels and default value."""
    assert SensitivityLevel.NORMAL == "normal"
    assert SensitivityLevel.SENSITIVE == "sensitive"
    assert SensitivityLevel.INTERNAL == "internal"

    item = MemoryItemCreate(kind=MemoryKind.FACT, content="User likes python")
    assert item.sensitivity == SensitivityLevel.NORMAL


def test_confidence_validation():
    """Verify confidence must be bounded in [0.0, 1.0]."""
    # Valid
    valid_item = MemoryItemCreate(
        kind=MemoryKind.FACT,
        content="User lives in Bangalore",
        confidence=0.95,
    )
    assert valid_item.confidence == 0.95

    # Valid boundary values
    assert MemoryItemCreate(kind=MemoryKind.FACT, content="test", confidence=0.0).confidence == 0.0
    assert MemoryItemCreate(kind=MemoryKind.FACT, content="test", confidence=1.0).confidence == 1.0

    # Invalid < 0.0
    with pytest.raises(ValidationError):
        MemoryItemCreate(kind=MemoryKind.FACT, content="test", confidence=-0.1)

    # Invalid > 1.0
    with pytest.raises(ValidationError):
        MemoryItemCreate(kind=MemoryKind.FACT, content="test", confidence=1.05)


def test_content_non_empty_validation():
    """Verify content cannot be blank or whitespace-only."""
    with pytest.raises(ValidationError, match="Memory content must not be blank"):
        MemoryItemCreate(kind=MemoryKind.FACT, content="   ")

    with pytest.raises(ValidationError):
        MemoryItemCreate(kind=MemoryKind.FACT, content="")


def test_timestamp_timezone_awareness():
    """Verify occurred_at and filter timestamps require timezone awareness."""
    naive_dt = datetime(2026, 10, 21, 12, 0, 0)
    aware_dt = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)

    # Naive timestamp should fail validation
    with pytest.raises(ValidationError, match="timezone-aware"):
        MemoryItemCreate(kind=MemoryKind.EPISODE, content="Morning checkin", occurred_at=naive_dt)

    # Timezone-aware succeeds
    item = MemoryItemCreate(
        kind=MemoryKind.EPISODE, content="Morning checkin", occurred_at=aware_dt
    )
    assert item.occurred_at == aware_dt


def test_provenance_and_inference_distinction():
    """Verify explicit vs inferred fact tracking."""
    item_read = MemoryItemRead(
        id=uuid4(),
        owner_id="user_123",
        kind=MemoryKind.FACT,
        content="Prefers concise code",
        confidence=0.8,
        approved=False,
        metadata={"is_inferred": True},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    prov = item_read.provenance
    assert prov.confidence == 0.8
    assert prov.is_inferred is True
    assert item_read.is_active is True


def test_skill_approval_default_and_immutability_on_create():
    """Verify MemoryItemCreate rejects caller-supplied approved field and skills
    cannot self-approve.
    """
    skill_item = MemoryItemCreate(
        kind=MemoryKind.SKILL,
        content="Run security audit on git repository",
    )
    # approved is not a caller-controlled field on creation
    assert "approved" not in MemoryItemCreate.model_fields
    assert hasattr(skill_item, "approved") is False

    # Callers cannot supply approved=True or approved=False on creation (extra forbidden)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MemoryItemCreate(
            kind=MemoryKind.SKILL,
            content="Run security audit on git repository",
            approved=True,  # type: ignore
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MemoryItemCreate(
            kind=MemoryKind.FACT,
            content="Normal fact",
            approved=True,  # type: ignore
        )


def test_memory_filter_deleted_items_default():
    """Verify MemoryFilter excludes deleted items by default."""
    filter_spec = MemoryFilter()
    assert filter_spec.include_deleted is False


# -----------------------------------------------------------------------------
# 2. SQLAlchemy Model Metadata Tests (Table, Columns, Constraints, Indexes)
# -----------------------------------------------------------------------------


def test_memory_model_table_structure():
    """Verify SQLAlchemy MemoryItemModel table columns and types."""
    assert MemoryItemModel.__tablename__ == "memory_items"
    table = MemoryItemModel.__table__

    assert "id" in table.c
    assert "owner_id" in table.c
    assert "kind" in table.c
    assert "title" in table.c
    assert "content" in table.c
    assert "embedding" in table.c
    assert "source_type" in table.c
    assert "source_ref" in table.c
    assert "occurred_at" in table.c
    assert "confidence" in table.c
    assert "sensitivity" in table.c
    assert "approved" in table.c
    assert "deleted_at" in table.c
    assert "metadata" in table.c
    assert "created_at" in table.c
    assert "updated_at" in table.c


def test_memory_model_id_server_default():
    """Verify memory_items.id has PostgreSQL gen_random_uuid() server default."""
    table = MemoryItemModel.__table__
    assert table.c.id.server_default is not None
    assert "gen_random_uuid()" in str(table.c.id.server_default.arg)


def test_memory_model_constraints():
    """Verify check constraints and naming conventions on MemoryItemModel."""
    table = MemoryItemModel.__table__
    constraint_names = [c.name for c in table.constraints]

    assert "ck_memory_items_kind_valid" in constraint_names
    assert "ck_memory_items_confidence_range" in constraint_names
    assert "ck_memory_items_sensitivity_valid" in constraint_names


def test_memory_model_indexes():
    """Verify active retrieval partial indexes on MemoryItemModel."""
    table = MemoryItemModel.__table__
    index_names = [idx.name for idx in table.indexes]

    assert "ix_memory_items_owner_kind_active" in index_names
    assert "ix_memory_items_owner_occurred_at" in index_names


def test_models_init_import():
    """Verify MemoryItemModel is exported cleanly from cortexstone.db.models."""
    from cortexstone.db.models import Base, MemoryItemModel, TimestampMixin

    assert MemoryItemModel is not None
    assert issubclass(MemoryItemModel, Base)
    assert issubclass(MemoryItemModel, TimestampMixin)


# -----------------------------------------------------------------------------
# 3. Embedding Interface Tests
# -----------------------------------------------------------------------------


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock implementation of EmbeddingProvider for interface verification."""

    @property
    def provider_name(self) -> str:
        return "mock-provider"

    @property
    def dimension(self) -> int:
        return 384

    async def embed_text(self, text: str):
        return [0.1] * self.dimension

    async def embed_batch(self, texts):
        return [[0.1] * self.dimension for _ in texts]


@pytest.mark.anyio
async def test_mock_embedding_provider_interface():
    """Verify EmbeddingProvider subclass adheres to the contract."""
    provider = MockEmbeddingProvider()
    assert provider.provider_name == "mock-provider"
    assert provider.dimension == 384

    single_emb = await provider.embed_text("Test query")
    assert len(single_emb) == 384
    assert single_emb[0] == 0.1

    batch_emb = await provider.embed_batch(["text 1", "text 2"])
    assert len(batch_emb) == 2
    assert len(batch_emb[0]) == 384
