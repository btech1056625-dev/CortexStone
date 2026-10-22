"""SQLAlchemy implementation of the MemoryRepositoryInterface.

Enforces mandatory owner scoping, parameterized SQL/ORM expressions,
deterministic ordering, soft deletion, and verifiable hard deletion.
"""

from uuid import UUID

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cortexstone.db.base import utc_now
from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemUpdate,
)


class SqlAlchemyMemoryRepository(MemoryRepositoryInterface):
    """SQLAlchemy async repository for memory items.

    Transaction boundaries:
    This repository performs operations on the provided `session`. It calls
    `session.flush()` to ensure IDs and database constraints are applied,
    but does NOT call `session.commit()`. The calling service or unit-of-work
    is responsible for transaction commit or rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an active AsyncSession.

        Args:
            session: SQLAlchemy AsyncSession.
        """
        self._session = session

    async def create(
        self,
        owner_id: str,
        item: MemoryItemCreate,
    ) -> MemoryItemModel:
        """Create and persist a new memory record for the specified owner.

        Assigns owner_id strictly from the method argument.
        Does not log content or sensitive attributes.
        """
        if not owner_id or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string.")

        # Serialize metadata and preserve is_inferred flag if supplied
        metadata_dict = dict(item.metadata)
        if item.is_inferred:
            metadata_dict["is_inferred"] = True

        model = MemoryItemModel(
            owner_id=owner_id.strip(),
            kind=item.kind.value,
            title=item.title,
            content=item.content,
            source_type=item.source_type,
            source_ref=item.source_ref,
            occurred_at=item.occurred_at,
            confidence=item.confidence,
            sensitivity=item.sensitivity.value,
            approved=item.approved,
            metadata_=metadata_dict,
        )

        self._session.add(model)
        await self._session.flush()
        return model

    async def get_by_id(
        self,
        owner_id: str,
        memory_id: UUID,
        include_deleted: bool = False,
    ) -> MemoryItemModel | None:
        """Fetch a single memory item by memory ID scoped to its owner.

        Filters strictly by both owner_id and id. Excludes soft-deleted records
        unless include_deleted is explicitly requested.
        """
        if not owner_id or not memory_id:
            return None

        stmt = select(MemoryItemModel).where(
            MemoryItemModel.id == memory_id,
            MemoryItemModel.owner_id == owner_id.strip(),
        )

        if not include_deleted:
            stmt = stmt.where(MemoryItemModel.deleted_at.is_(None))

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        owner_id: str,
        filter_params: MemoryFilter | None = None,
    ) -> list[MemoryItemModel]:
        """List memory items belonging to the owner matching filter criteria.

        Always filters by owner_id and excludes deleted records by default.
        Orders deterministically by (created_at DESC, id DESC).
        """
        if not owner_id or not owner_id.strip():
            return []

        if filter_params is None:
            filter_params = MemoryFilter()

        stmt = select(MemoryItemModel).where(MemoryItemModel.owner_id == owner_id.strip())

        # Soft-deletion exclusion
        if not filter_params.include_deleted:
            stmt = stmt.where(MemoryItemModel.deleted_at.is_(None))

        # Kind filter
        if filter_params.kind is not None:
            stmt = stmt.where(MemoryItemModel.kind == filter_params.kind.value)

        # Source type filter
        if filter_params.source_type is not None:
            stmt = stmt.where(MemoryItemModel.source_type == filter_params.source_type)

        # Sensitivity filter
        if filter_params.sensitivity is not None:
            stmt = stmt.where(MemoryItemModel.sensitivity == filter_params.sensitivity.value)

        # Approved-only filter (e.g. for approved skills)
        if filter_params.approved_only is not None:
            stmt = stmt.where(MemoryItemModel.approved.is_(filter_params.approved_only))

        # Temporal filters
        if filter_params.occurred_after is not None:
            stmt = stmt.where(MemoryItemModel.occurred_at >= filter_params.occurred_after)

        if filter_params.occurred_before is not None:
            stmt = stmt.where(MemoryItemModel.occurred_at <= filter_params.occurred_before)

        # Deterministic ordering
        stmt = stmt.order_by(
            desc(MemoryItemModel.created_at),
            desc(MemoryItemModel.id),
        )

        # Bounded pagination
        stmt = stmt.offset(filter_params.offset).limit(filter_params.limit)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        owner_id: str,
        memory_id: UUID,
        update_data: MemoryItemUpdate,
        allow_approval_change: bool = False,
    ) -> MemoryItemModel | None:
        """Update an existing active memory item owned by owner_id.

        Protections:
        1. Owner ID cannot be changed.
        2. Soft-deleted records cannot be updated or silently reactivated.
        3. `approved` state cannot be toggled unless `allow_approval_change=True`.
        4. Updates `updated_at` to UTC now.
        """
        if not owner_id or not memory_id:
            return None

        # Fetch active target record
        target = await self.get_by_id(
            owner_id=owner_id,
            memory_id=memory_id,
            include_deleted=False,
        )
        if target is None:
            return None

        # Apply update fields
        if update_data.title is not None:
            target.title = update_data.title

        if update_data.content is not None:
            target.content = update_data.content

        if update_data.occurred_at is not None:
            target.occurred_at = update_data.occurred_at

        if update_data.confidence is not None:
            target.confidence = update_data.confidence

        if update_data.sensitivity is not None:
            target.sensitivity = update_data.sensitivity.value

        if update_data.metadata is not None:
            # Merge or replace metadata
            merged_meta = dict(target.metadata_ or {})
            merged_meta.update(update_data.metadata)
            target.metadata_ = merged_meta

        # Restricted approval update
        if update_data.approved is not None:
            if not allow_approval_change:
                raise PermissionError(
                    "Changing memory approval status is restricted and requires "
                    "explicit authorization."
                )
            target.approved = update_data.approved

        target.updated_at = utc_now()
        await self._session.flush()
        return target

    async def soft_delete(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> bool:
        """Mark an active memory item as deleted.

        Sets deleted_at = utc_now().
        Returns True if an active record was found, owned, and marked deleted.
        Returns False if not found, owned by someone else, or already deleted.
        """
        if not owner_id or not memory_id:
            return False

        now = utc_now()
        stmt = (
            update(MemoryItemModel)
            .where(
                MemoryItemModel.id == memory_id,
                MemoryItemModel.owner_id == owner_id.strip(),
                MemoryItemModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )

        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0

    async def hard_delete(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> bool:
        """Physically delete a memory record from the database.

        Requires both memory ID and owner ID.
        Returns True if row was deleted, False if no matching row existed.
        """
        if not owner_id or not memory_id:
            return False

        stmt = delete(MemoryItemModel).where(
            MemoryItemModel.id == memory_id,
            MemoryItemModel.owner_id == owner_id.strip(),
        )

        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0
