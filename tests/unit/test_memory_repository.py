"""Unit tests for SqlAlchemyMemoryRepository and ownership scoping.

Tests repository query construction, owner filtering, soft-delete, hard-delete,
and update security without requiring a live PostgreSQL database.
Uses AsyncSession mocks and SQLAlchemy statement inspection.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.repositories.memory_repo import SqlAlchemyMemoryRepository
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryKind,
    SensitivityLevel,
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
    assert mock_session.add.called
    assert mock_session.flush.called


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

    dt_after = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    dt_before = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)

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
