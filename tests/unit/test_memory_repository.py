"""Unit tests for SqlAlchemyMemoryRepository and ownership scoping.

Tests repository query construction, owner filtering, soft-delete, hard-delete,
and update security without requiring a live PostgreSQL database.
Uses AsyncSession mocks and SQLAlchemy statement inspection.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.repositories.memory_repo import SqlAlchemyMemoryRepository
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryKind,
)


def get_compiled_sql(stmt) -> str:
    """Compile a SQLAlchemy statement using the PostgreSQL dialect with literal binds."""
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


# -----------------------------------------------------------------------------
# 1. Creation and Ownership Assignment
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_assigns_supplied_owner_id():
    """Verify create assigns the supplied owner_id argument strictly."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # add is synchronous in AsyncSession
    repo = SqlAlchemyMemoryRepository(mock_session)

    item_in = MemoryItemCreate(
        kind=MemoryKind.FACT,
        content="User likes dark mode",
        confidence=0.9,
    )

    created_model = await repo.create(owner_id="user_abc", item=item_in)

    assert created_model.owner_id == "user_abc"
    assert created_model.kind == "fact"
    assert created_model.content == "User likes dark mode"
    assert created_model.confidence == 0.9
    assert created_model.approved is False
    assert mock_session.add.called
    assert mock_session.flush.called


@pytest.mark.anyio
async def test_create_skill_always_defaults_approved_false():
    """Verify creating a skill always sets approved=False in repository logic."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    repo = SqlAlchemyMemoryRepository(mock_session)

    skill_in = MemoryItemCreate(
        kind=MemoryKind.SKILL,
        content="Run bash command inside sandbox",
    )
    created_skill = await repo.create(owner_id="user_admin", item=skill_in)
    assert created_skill.kind == "skill"
    assert created_skill.approved is False

    # Non-skill creation also initializes approved=False
    fact_in = MemoryItemCreate(
        kind=MemoryKind.FACT,
        content="User time zone is America/New_York",
    )
    created_fact = await repo.create(owner_id="user_admin", item=fact_in)
    assert created_fact.kind == "fact"
    assert created_fact.approved is False


@pytest.mark.anyio
async def test_create_rejects_empty_owner_id():
    """Verify create raises ValueError if owner_id is empty or whitespace."""
    mock_session = AsyncMock()
    repo = SqlAlchemyMemoryRepository(mock_session)

    item_in = MemoryItemCreate(kind=MemoryKind.FACT, content="test")
    with pytest.raises(ValueError, match="owner_id must be a non-empty string"):
        await repo.create(owner_id="   ", item=item_in)


# -----------------------------------------------------------------------------
# 2. get_by_id Query Construction & Isolation
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_by_id_statement_includes_owner_and_deleted_filter():
    """Verify get_by_id query expression includes owner_id, memory id, and deleted_at IS NULL."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyMemoryRepository(mock_session)
    mem_id = uuid4()

    await repo.get_by_id(owner_id="user_123", memory_id=mem_id, include_deleted=False)
    assert mock_session.execute.called

    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)

    assert "memory_items.id = " in sql_str
    assert "memory_items.owner_id = 'user_123'" in sql_str
    assert "memory_items.deleted_at IS NULL" in sql_str


@pytest.mark.anyio
async def test_get_by_id_with_include_deleted():
    """Verify include_deleted=True omits deleted_at IS NULL condition."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyMemoryRepository(mock_session)
    mem_id = uuid4()

    await repo.get_by_id(owner_id="user_123", memory_id=mem_id, include_deleted=True)
    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)

    assert "memory_items.id = " in sql_str
    assert "memory_items.owner_id = 'user_123'" in sql_str
    assert "memory_items.deleted_at IS NULL" not in sql_str


# -----------------------------------------------------------------------------
# 3. list Query Construction & Filters
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_statement_owner_filtering_and_pagination():
    """Verify list query applies owner_id filter, excludes deleted records, and paginates."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyMemoryRepository(mock_session)

    filter_params = MemoryFilter(
        kind=MemoryKind.FACT,
        limit=10,
        offset=5,
    )

    items = await repo.list(owner_id="user_xyz", filter_params=filter_params)
    assert items == []
    assert mock_session.execute.called

    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)

    assert "memory_items.owner_id = 'user_xyz'" in sql_str
    assert "memory_items.kind = 'fact'" in sql_str
    assert "memory_items.deleted_at IS NULL" in sql_str
    assert "LIMIT 10" in sql_str
    assert "OFFSET 5" in sql_str
    assert "ORDER BY memory_items.created_at DESC" in sql_str


@pytest.mark.anyio
async def test_list_temporal_and_approval_filters():
    """Verify list applies temporal bounds and approved_only filter."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyMemoryRepository(mock_session)

    dt_after = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    dt_before = datetime(2026, 10, 20, 0, 0, 0, tzinfo=UTC)

    filter_params = MemoryFilter(
        approved_only=True,
        occurred_after=dt_after,
        occurred_before=dt_before,
    )

    await repo.list(owner_id="user_xyz", filter_params=filter_params)
    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)

    assert "memory_items.approved IS true" in sql_str
    assert "memory_items.occurred_at >=" in sql_str
    assert "memory_items.occurred_at <=" in sql_str


# -----------------------------------------------------------------------------
# 4. update Protections
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_cannot_change_owner_id_or_reactivate():
    """Verify update cannot alter owner_id or clear deleted_at."""
    mock_session = AsyncMock()
    repo = SqlAlchemyMemoryRepository(mock_session)

    mem_id = uuid4()
    existing_model = MemoryItemModel(
        id=mem_id,
        owner_id="user_owner",
        kind="fact",
        content="Original content",
        deleted_at=None,
    )

    # Mock get_by_id returning existing model
    repo.get_by_id = AsyncMock(return_value=existing_model)

    update_in = MemoryItemUpdate(content="Updated content")
    updated = await repo.update("user_owner", mem_id, update_in)

    assert updated is not None
    assert updated.content == "Updated content"
    assert updated.owner_id == "user_owner"  # Ownership preserved
    assert updated.deleted_at is None


@pytest.mark.anyio
async def test_update_approval_status_requires_explicit_authorization():
    """Verify callers cannot approve skills via normal update without authorization flag."""
    mock_session = AsyncMock()
    repo = SqlAlchemyMemoryRepository(mock_session)

    mem_id = uuid4()
    existing_skill = MemoryItemModel(
        id=mem_id,
        owner_id="user_owner",
        kind="skill",
        content="Execute task",
        approved=False,
    )
    repo.get_by_id = AsyncMock(return_value=existing_skill)

    update_in = MemoryItemUpdate(approved=True)

    # Without allow_approval_change, should raise PermissionError
    with pytest.raises(PermissionError, match="restricted"):
        await repo.update("user_owner", mem_id, update_in, allow_approval_change=False)

    # With allow_approval_change=True, succeeds
    res = await repo.update("user_owner", mem_id, update_in, allow_approval_change=True)
    assert res is not None
    assert res.approved is True


# -----------------------------------------------------------------------------
# 5. Soft-Delete and Hard-Delete Statement Construction
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_soft_delete_statement_sets_deleted_at_with_owner_id():
    """Verify soft_delete executes UPDATE with owner_id and deleted_at IS NULL."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyMemoryRepository(mock_session)
    mem_id = uuid4()

    success = await repo.soft_delete(owner_id="user_123", memory_id=mem_id)
    assert success is True
    assert mock_session.execute.called

    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)

    assert "UPDATE memory_items SET" in sql_str
    assert "deleted_at=" in sql_str
    assert "memory_items.id = " in sql_str
    assert "memory_items.owner_id = 'user_123'" in sql_str
    assert "memory_items.deleted_at IS NULL" in sql_str


@pytest.mark.anyio
async def test_hard_delete_statement_includes_owner_id():
    """Verify hard_delete executes DELETE strictly scoped to owner_id."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyMemoryRepository(mock_session)
    mem_id = uuid4()

    success = await repo.hard_delete(owner_id="user_123", memory_id=mem_id)
    assert success is True
    assert mock_session.execute.called

    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)

    assert "DELETE FROM memory_items" in sql_str
    assert "memory_items.id = " in sql_str
    assert "memory_items.owner_id = 'user_123'" in sql_str


@pytest.mark.anyio
async def test_interface_compliance():
    """Verify SqlAlchemyMemoryRepository adheres to MemoryRepositoryInterface."""
    assert issubclass(SqlAlchemyMemoryRepository, MemoryRepositoryInterface)


# -----------------------------------------------------------------------------
# 6. Vector Embedding and Semantic Search Tests
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_stores_embedding():
    """Verify create assigns pre-computed embedding vector to model."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    repo = SqlAlchemyMemoryRepository(mock_session)
    embedding = [0.05] * 384

    item_in = MemoryItemCreate(
        kind=MemoryKind.FACT,
        content="User prefers Python 3.12",
    )
    created = await repo.create(owner_id="user_embed", item=item_in, embedding=embedding)
    assert created.owner_id == "user_embed"
    assert created.embedding == embedding


@pytest.mark.anyio
async def test_update_updates_embedding():
    """Verify update refreshes embedding vector when provided."""
    mock_session = AsyncMock()
    existing = MemoryItemModel(
        id=uuid4(),
        owner_id="user_embed",
        kind="fact",
        content="Old content",
        sensitivity="normal",
        embedding=[0.01] * 384,
    )
    repo = SqlAlchemyMemoryRepository(mock_session)
    repo.get_by_id = AsyncMock(return_value=existing)

    new_embedding = [0.99] * 384
    update_in = MemoryItemUpdate(content="Updated content")
    updated = await repo.update(
        owner_id="user_embed",
        memory_id=existing.id,
        update_data=update_in,
        embedding=new_embedding,
    )
    assert updated is not None
    assert updated.content == "Updated content"
    assert updated.embedding == new_embedding


@pytest.mark.anyio
async def test_search_semantic_pgvector_query_structure():
    """Verify search_semantic generates owner-scoped SQL with pgvector distance operator."""
    mock_session = AsyncMock()
    mock_res = MagicMock()
    fake_model = MemoryItemModel(
        id=uuid4(),
        owner_id="user_search",
        kind="fact",
        content="Sample content",
        embedding=[0.1] * 384,
    )
    mock_res.all.return_value = [(fake_model, 0.15)]
    mock_res.scalars.return_value.all.return_value = [fake_model]
    mock_session.execute.return_value = mock_res
    repo = SqlAlchemyMemoryRepository(mock_session)

    results = await repo.search_semantic(
        owner_id="user_search",
        query_vector=[0.1] * 384,
        top_k=5,
    )
    assert len(results) == 1
    assert results[0][0].id == fake_model.id
    assert results[0][1] == 0.85  # 1.0 - 0.15

    stmt = mock_session.execute.call_args[0][0]
    sql_str = get_compiled_sql(stmt)
    assert "memory_items.owner_id = 'user_search'" in sql_str
    assert "memory_items.deleted_at IS NULL" in sql_str
    assert "<=>" in sql_str
    assert "LIMIT 5" in sql_str


@pytest.mark.anyio
async def test_search_semantic_empty_owner_returns_empty():
    """Verify search_semantic returns empty list on blank owner."""
    mock_session = AsyncMock()
    repo = SqlAlchemyMemoryRepository(mock_session)
    res = await repo.search_semantic(owner_id="  ", query_vector=[0.1] * 384)
    assert res == []
    assert not mock_session.execute.called


@pytest.mark.anyio
async def test_search_semantic_empty_query_raises_value_error():
    """Verify search_semantic raises ValueError on empty query vector."""
    mock_session = AsyncMock()
    repo = SqlAlchemyMemoryRepository(mock_session)
    with pytest.raises(ValueError, match="query_vector must not be empty"):
        await repo.search_semantic(owner_id="user_1", query_vector=[])
