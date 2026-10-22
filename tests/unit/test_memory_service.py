"""Unit tests for application-level MemoryService and verifiable forgetting."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cortexstone.application.memory.service import (
    DeletionReceipt,
    MemoryExport,
    MemoryService,
)
from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryItemUpdate,
    MemoryKind,
    SensitivityLevel,
    utc_now,
)
from cortexstone.security.audit.service import InMemoryAuditLogger


def create_fake_model(
    owner_id: str,
    memory_id=None,
    kind="fact",
    content="Test memory content",
    sensitivity="normal",
    approved=False,
    deleted_at=None,
) -> MemoryItemModel:
    """Helper to instantiate a valid MemoryItemModel."""
    return MemoryItemModel(
        id=memory_id or uuid4(),
        owner_id=owner_id,
        kind=kind,
        content=content,
        sensitivity=sensitivity,
        approved=approved,
        deleted_at=deleted_at,
        metadata_={"test_key": "test_val"},
        created_at=utc_now(),
        updated_at=utc_now(),
    )


# -----------------------------------------------------------------------------
# 1. Create, Get, List, and Update Delegation Tests
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_memory_delegates_and_logs_audit():
    """Verify create_memory delegates to repository and emits content-free audit event."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    fake_model = create_fake_model(owner_id="user_1")
    mock_repo.create.return_value = fake_model

    audit_logger = InMemoryAuditLogger()
    service = MemoryService(repository=mock_repo, audit_logger=audit_logger)

    create_in = MemoryItemCreate(
        kind=MemoryKind.FACT,
        content="User loves rust",
        sensitivity=SensitivityLevel.NORMAL,
    )

    result = await service.create_memory(owner_id="user_1", item=create_in)

    assert isinstance(result, MemoryItemRead)
    assert result.owner_id == "user_1"
    assert result.content == "Test memory content"
    mock_repo.create.assert_called_once_with(owner_id="user_1", item=create_in)

    # Check audit event
    assert len(audit_logger.events) == 1
    ev = audit_logger.events[0]
    assert ev.event_type == "memory.create"
    assert ev.owner_id == "user_1"
    assert ev.resource_id == result.id
    # Assert private memory content is NOT present anywhere in audit event
    assert "User loves rust" not in str(ev.details)
    assert "Test memory content" not in str(ev.details)


@pytest.mark.anyio
async def test_create_memory_rejects_empty_owner_id():
    """Verify create_memory raises ValueError on invalid owner_id."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    service = MemoryService(repository=mock_repo)

    create_in = MemoryItemCreate(kind=MemoryKind.FACT, content="test")
    with pytest.raises(ValueError, match="owner_id must be a non-empty string"):
        await service.create_memory(owner_id="   ", item=create_in)


@pytest.mark.anyio
async def test_get_memory_delegates_owner_id():
    """Verify get_memory queries with owner_id and exclude_deleted=False."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mem_id = uuid4()
    fake_model = create_fake_model(owner_id="user_1", memory_id=mem_id)
    mock_repo.get_by_id.return_value = fake_model

    service = MemoryService(repository=mock_repo)
    result = await service.get_memory(owner_id="user_1", memory_id=mem_id)

    assert result is not None
    assert result.id == mem_id
    mock_repo.get_by_id.assert_called_once_with(
        owner_id="user_1",
        memory_id=mem_id,
        include_deleted=False,
    )


@pytest.mark.anyio
async def test_get_memory_returns_none_if_missing_or_mismatched_owner():
    """Verify get_memory returns None if repository returns None."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mock_repo.get_by_id.return_value = None

    service = MemoryService(repository=mock_repo)
    result = await service.get_memory(owner_id="user_2", memory_id=uuid4())
    assert result is None


@pytest.mark.anyio
async def test_list_memories_delegates_filter():
    """Verify list_memories propagates owner_id and filter options."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    m1 = create_fake_model(owner_id="user_1")
    m2 = create_fake_model(owner_id="user_1")
    mock_repo.list.return_value = [m1, m2]

    service = MemoryService(repository=mock_repo)
    filters = MemoryFilter(kind=MemoryKind.FACT, limit=5)

    results = await service.list_memories(owner_id="user_1", filter_params=filters)
    assert len(results) == 2
    assert results[0].id == m1.id
    mock_repo.list.assert_called_once_with(owner_id="user_1", filter_params=filters)


@pytest.mark.anyio
async def test_update_memory_delegates_and_respects_approval():
    """Verify update_memory passes update data and allow_approval_change flag."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mem_id = uuid4()
    updated_fake = create_fake_model(owner_id="user_1", memory_id=mem_id, content="new")
    mock_repo.update.return_value = updated_fake

    audit_logger = InMemoryAuditLogger()
    service = MemoryService(repository=mock_repo, audit_logger=audit_logger)

    update_in = MemoryItemUpdate(content="new")
    res = await service.update_memory(
        owner_id="user_1",
        memory_id=mem_id,
        update_data=update_in,
        allow_approval_change=False,
    )

    assert res is not None
    assert res.content == "new"
    mock_repo.update.assert_called_once_with(
        owner_id="user_1",
        memory_id=mem_id,
        update_data=update_in,
        allow_approval_change=False,
    )
    assert len(audit_logger.events) == 1
    assert audit_logger.events[0].event_type == "memory.update"


# -----------------------------------------------------------------------------
# 2. Verifiable Forgetting Workflow Tests
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forget_memory_success_and_receipt_content_free():
    """Verify forget_memory verifies exclusion, returns content-free receipt, and logs audit."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mem_id = uuid4()

    # Step 1: Initial query returns active item
    active_model = create_fake_model(owner_id="user_1", memory_id=mem_id, deleted_at=None)
    # Step 3: Verification query returns None (memory is no longer accessible)
    mock_repo.get_by_id.side_effect = [active_model, None]
    mock_repo.soft_delete.return_value = True

    audit_logger = InMemoryAuditLogger()
    service = MemoryService(repository=mock_repo, audit_logger=audit_logger)

    receipt = await service.forget_memory(owner_id="user_1", memory_id=mem_id)

    assert isinstance(receipt, DeletionReceipt)
    assert receipt.memory_id == mem_id
    assert receipt.owner_id == "user_1"
    assert receipt.verified_excluded is True
    assert receipt.status == "forgotten"

    # Verify receipt and audit contain NO private content
    receipt_dict = receipt.model_dump()
    assert "content" not in receipt_dict
    assert "embedding" not in receipt_dict

    assert len(audit_logger.events) == 1
    ev = audit_logger.events[0]
    assert ev.event_type == "memory.forget"
    assert ev.status == "success"
    assert "content" not in ev.details


@pytest.mark.anyio
async def test_forget_memory_verification_failure_raises():
    """Verify forget_memory raises RuntimeError if ordinary retrieval still returns item."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mem_id = uuid4()

    active_model = create_fake_model(owner_id="user_1", memory_id=mem_id, deleted_at=None)
    # Both initial query and verification query return the active item!
    mock_repo.get_by_id.side_effect = [active_model, active_model]
    mock_repo.soft_delete.return_value = True

    audit_logger = InMemoryAuditLogger()
    service = MemoryService(repository=mock_repo, audit_logger=audit_logger)

    with pytest.raises(RuntimeError, match="forget verification failed"):
        await service.forget_memory(owner_id="user_1", memory_id=mem_id)

    # Failure audit event recorded
    assert len(audit_logger.events) == 1
    assert audit_logger.events[0].status == "failure"


@pytest.mark.anyio
async def test_forget_memory_idempotent_already_forgotten():
    """Verify forget_memory is idempotent if record is already deleted."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mem_id = uuid4()
    del_time = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)

    already_deleted = create_fake_model(
        owner_id="user_1",
        memory_id=mem_id,
        deleted_at=del_time,
    )
    mock_repo.get_by_id.return_value = already_deleted

    service = MemoryService(repository=mock_repo)
    receipt = await service.forget_memory(owner_id="user_1", memory_id=mem_id)

    assert receipt.status == "already_forgotten"
    assert receipt.verified_excluded is True
    assert mock_repo.soft_delete.called is False


@pytest.mark.anyio
async def test_forget_memory_not_found():
    """Verify forget_memory handles non-existent or other-user records cleanly."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mock_repo.get_by_id.return_value = None

    service = MemoryService(repository=mock_repo)
    receipt = await service.forget_memory(owner_id="user_1", memory_id=uuid4())

    assert receipt.status == "not_found"
    assert receipt.verified_excluded is True


# -----------------------------------------------------------------------------
# 3. Export Operations
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_memories_owner_scoped_and_bounded():
    """Verify export_memories returns active memories for authenticated owner only."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    m1 = create_fake_model(owner_id="user_alpha")
    m2 = create_fake_model(owner_id="user_alpha")
    mock_repo.list.return_value = [m1, m2]

    service = MemoryService(repository=mock_repo)
    export_result = await service.export_memories(owner_id="user_alpha", max_items=50)

    assert isinstance(export_result, MemoryExport)
    assert export_result.owner_id == "user_alpha"
    assert export_result.total_count == 2
    assert len(export_result.items) == 2

    # Check filter applied to repository
    call_args = mock_repo.list.call_args[1]
    assert call_args["owner_id"] == "user_alpha"
    assert call_args["filter_params"].include_deleted is False
    assert call_args["filter_params"].limit == 50
