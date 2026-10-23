"""Abstract repository interface for CortexStone memory persistence.

Enforces mandatory owner-scoped access on every query and mutation.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemUpdate,
)


class MemoryRepositoryInterface(ABC):
    """Abstract asynchronous repository interface for memory storage.

    Every method requires an explicit, non-optional `owner_id`.
    Callers (services, API) must supply the authenticated owner identity;
    arbitrary or client-supplied ownership assertions are not accepted.
    """

    @abstractmethod
    async def create(
        self,
        owner_id: str,
        item: MemoryItemCreate,
    ) -> MemoryItemModel:
        """Create and persist a new memory record for the specified owner.

        Args:
            owner_id: Authenticated owner ID. Assigned to the record.
            item: Validated creation schema.

        Returns:
            The created and persisted MemoryItemModel instance.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(
        self,
        owner_id: str,
        memory_id: UUID,
        include_deleted: bool = False,
    ) -> MemoryItemModel | None:
        """Fetch a single memory item by memory ID scoped to its owner.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: Target memory UUID.
            include_deleted: Whether to return soft-deleted records. Default False.

        Returns:
            MemoryItemModel if found, owned by owner_id, and not soft-deleted
            (unless include_deleted=True); otherwise None.
            Never reveals whether a record belonging to another owner exists.
        """
        raise NotImplementedError

    @abstractmethod
    async def list(
        self,
        owner_id: str,
        filter_params: MemoryFilter | None = None,
    ) -> list[MemoryItemModel]:
        """List memory items belonging to the owner matching filter criteria.

        Args:
            owner_id: Authenticated owner ID.
            filter_params: Filtering, pagination, and sorting options.

        Returns:
            List of matching MemoryItemModel instances ordered deterministically.
        """
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        owner_id: str,
        memory_id: UUID,
        update_data: MemoryItemUpdate,
        allow_approval_change: bool = False,
    ) -> MemoryItemModel | None:
        """Update an existing active memory item owned by owner_id.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: Target memory UUID.
            update_data: Validated update payload.
            allow_approval_change: Guard flag. Callers can only toggle `approved`
                status if explicitly authorized by the approval subsystem.

        Returns:
            Updated MemoryItemModel if found, owned, and active; otherwise None.
            Cannot change owner_id or reactivate soft-deleted records.
        """
        raise NotImplementedError

    @abstractmethod
    async def soft_delete(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> bool:
        """Mark a memory item as deleted by setting deleted_at to UTC now.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: Target memory UUID.

        Returns:
            True if the record was found, owned, active, and soft-deleted.
            False if the record did not exist, was already deleted, or belonged to another owner.
        """
        raise NotImplementedError

    @abstractmethod
    async def hard_delete(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> bool:
        """Permanently delete a memory record from the database.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: Target memory UUID.

        Returns:
            True if matching row was physically deleted.
            False if no matching row existed for this owner.
        """
        raise NotImplementedError
