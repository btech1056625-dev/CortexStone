"""Application-level memory orchestration service.

Orchestrates memory creation, retrieval, listing, updates, verifiable
forgetting, and owner-scoped export using injected repository and audit interfaces.

Security & Architectural Invariants:
1. Every method requires an explicit, authenticated `owner_id`.
2. Client/model payloads cannot set or override `owner_id`.
3. Verifiable forgetting performs soft deletion and actively asserts that the
   record is no longer retrievable via ordinary queries before returning a
   content-free DeletionReceipt.
4. Audit records contain no deleted memory content, secrets, or embeddings.
5. Export operations are strictly owner-scoped and bounded.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cortexstone.db.base import utc_now
from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.retrieval.retriever import (
    MemoryRetrievalService,
    MemoryRetrieverInterface,
    RetrievalRequest,
    RetrievalResult,
)
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemRead,
    MemoryItemUpdate,
    MemoryKind,
    SensitivityLevel,
)
from cortexstone.security.audit.service import AuditEvent, AuditLoggerInterface


class DeletionReceipt(BaseModel):
    """Content-free receipt confirming the verifiable deletion of a memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_id: UUID
    owner_id: str
    deleted_at: datetime
    verified_excluded: bool = Field(
        ...,
        description="True if ordinary retrieval confirmed the memory is no longer accessible.",
    )
    status: str = Field(
        ...,
        description="'forgotten', 'already_forgotten', or 'not_found'.",
    )


class MemoryExport(BaseModel):
    """Export container for a user's active memories."""

    model_config = ConfigDict(frozen=True)

    owner_id: str
    exported_at: datetime
    total_count: int
    items: list[MemoryItemRead]


class MemoryService:
    """Application-level memory service orchestrating persistence and lifecycle."""

    def __init__(
        self,
        repository: MemoryRepositoryInterface,
        audit_logger: AuditLoggerInterface | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        retrieval_service: MemoryRetrieverInterface | None = None,
    ) -> None:
        """Initialize MemoryService with injected repository, optional audit logger and embedder.

        Args:
            repository: Conforming MemoryRepositoryInterface implementation.
            audit_logger: Optional AuditLoggerInterface implementation for lifecycle events.
            embedding_provider: Optional EmbeddingProvider for semantic embeddings.
            retrieval_service: Optional MemoryRetrieverInterface implementation.
        """
        self._repository = repository
        self._audit_logger = audit_logger
        self._embedding_provider = embedding_provider
        self._retrieval_service = retrieval_service or MemoryRetrievalService(
            repository=repository,
            embedding_provider=embedding_provider,
        )

    async def create_memory(
        self,
        owner_id: str,
        item: MemoryItemCreate,
    ) -> MemoryItemRead:
        """Create a new memory item for the authenticated owner.

        Args:
            owner_id: Authenticated owner ID.
            item: Validated creation schema.

        Returns:
            MemoryItemRead domain model.
        """
        if not owner_id or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string.")

        embedding: list[float] | None = None
        if self._embedding_provider is not None:
            embedding = await self._embedding_provider.embed_document(item.content)

        if embedding is not None:
            model = await self._repository.create(
                owner_id=owner_id.strip(),
                item=item,
                embedding=embedding,
            )
        else:
            model = await self._repository.create(
                owner_id=owner_id.strip(),
                item=item,
            )
        read_item = MemoryItemRead.model_validate(model)

        if self._audit_logger:
            await self._audit_logger.log_event(
                AuditEvent(
                    event_type="memory.create",
                    owner_id=owner_id.strip(),
                    resource_id=read_item.id,
                    details={
                        "kind": read_item.kind.value,
                        "sensitivity": read_item.sensitivity.value,
                    },
                )
            )

        return read_item

    async def get_memory(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> MemoryItemRead | None:
        """Retrieve an active memory item by ID for the authenticated owner.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: UUID of the target memory.

        Returns:
            MemoryItemRead if found, owned, and active; otherwise None.
        """
        if not owner_id or not owner_id.strip() or not memory_id:
            return None

        model = await self._repository.get_by_id(
            owner_id=owner_id.strip(),
            memory_id=memory_id,
            include_deleted=False,
        )
        if model is None:
            return None

        return MemoryItemRead.model_validate(model)

    async def list_memories(
        self,
        owner_id: str,
        filter_params: MemoryFilter | None = None,
    ) -> list[MemoryItemRead]:
        """List active memories for the authenticated owner matching filters.

        Args:
            owner_id: Authenticated owner ID.
            filter_params: Optional filters and pagination settings.

        Returns:
            List of MemoryItemRead domain models.
        """
        if not owner_id or not owner_id.strip():
            return []

        models = await self._repository.list(
            owner_id=owner_id.strip(),
            filter_params=filter_params,
        )
        return [MemoryItemRead.model_validate(m) for m in models]

    async def update_memory(
        self,
        owner_id: str,
        memory_id: UUID,
        update_data: MemoryItemUpdate,
        allow_approval_change: bool = False,
    ) -> MemoryItemRead | None:
        """Update an existing active memory item.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: UUID of the target memory.
            update_data: Validated update payload.
            allow_approval_change: Whether to allow toggling skill approval status.

        Returns:
            Updated MemoryItemRead if found and updated; otherwise None.
        """
        if not owner_id or not owner_id.strip() or not memory_id:
            return None

        embedding: list[float] | None = None
        if self._embedding_provider is not None and update_data.content is not None:
            embedding = await self._embedding_provider.embed_document(update_data.content)

        if embedding is not None:
            updated_model = await self._repository.update(
                owner_id=owner_id.strip(),
                memory_id=memory_id,
                update_data=update_data,
                allow_approval_change=allow_approval_change,
                embedding=embedding,
            )
        else:
            updated_model = await self._repository.update(
                owner_id=owner_id.strip(),
                memory_id=memory_id,
                update_data=update_data,
                allow_approval_change=allow_approval_change,
            )
        if updated_model is None:
            return None

        read_item = MemoryItemRead.model_validate(updated_model)

        if self._audit_logger:
            await self._audit_logger.log_event(
                AuditEvent(
                    event_type="memory.update",
                    owner_id=owner_id.strip(),
                    resource_id=read_item.id,
                    details={"kind": read_item.kind.value},
                )
            )

        return read_item

    async def forget_memory(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> DeletionReceipt:
        """Verifiably forget a memory item.

        Workflow:
        1. Query repository to check if record is active.
        2. If already missing or deleted, return idempotent receipt without error.
        3. Request soft deletion through the repository.
        4. Re-query repository to actively verify the record is no longer retrievable
           via ordinary queries.
        5. Log a content-free audit event (no private memory content).
        6. Return a content-free DeletionReceipt.

        Transaction / Durability Note:
        The repository operates within an active session. The soft deletion is flushed
        and verified within the session context, but durable database persistence
        depends on the surrounding transaction committing.

        Args:
            owner_id: Authenticated owner ID.
            memory_id: UUID of the target memory.

        Returns:
            DeletionReceipt documenting deletion timestamp and verification status.

        Raises:
            RuntimeError: If soft deletion reports success but verification query
                          still returns the record.
        """
        if not owner_id or not owner_id.strip() or not memory_id:
            raise ValueError("owner_id and memory_id must be provided.")

        clean_owner = owner_id.strip()

        # Step 1: Check existing status
        existing = await self._repository.get_by_id(
            owner_id=clean_owner,
            memory_id=memory_id,
            include_deleted=True,
        )

        if existing is None:
            # Record does not exist for this owner
            return DeletionReceipt(
                memory_id=memory_id,
                owner_id=clean_owner,
                deleted_at=utc_now(),
                verified_excluded=True,
                status="not_found",
            )

        if existing.deleted_at is not None:
            # Already soft-deleted
            return DeletionReceipt(
                memory_id=memory_id,
                owner_id=clean_owner,
                deleted_at=existing.deleted_at,
                verified_excluded=True,
                status="already_forgotten",
            )

        # Step 2: Request soft-delete
        deleted = await self._repository.soft_delete(
            owner_id=clean_owner,
            memory_id=memory_id,
        )
        if not deleted:
            return DeletionReceipt(
                memory_id=memory_id,
                owner_id=clean_owner,
                deleted_at=utc_now(),
                verified_excluded=False,
                status="not_found",
            )

        # Step 3: Verification - re-query via standard retrieval
        verify_check = await self._repository.get_by_id(
            owner_id=clean_owner,
            memory_id=memory_id,
            include_deleted=False,
        )
        if verify_check is not None:
            # Verification failed: memory is still returned by ordinary retrieval!
            if self._audit_logger:
                await self._audit_logger.log_event(
                    AuditEvent(
                        event_type="memory.forget",
                        owner_id=clean_owner,
                        resource_id=memory_id,
                        status="failure",
                        details={"error": "verification_failed_record_still_retrievable"},
                    )
                )
            raise RuntimeError(
                f"Memory forget verification failed: memory {memory_id} remains retrievable."
            )

        receipt = DeletionReceipt(
            memory_id=memory_id,
            owner_id=clean_owner,
            deleted_at=utc_now(),
            verified_excluded=True,
            status="forgotten",
        )

        # Step 4: Audit logging (content-free)
        if self._audit_logger:
            await self._audit_logger.log_event(
                AuditEvent(
                    event_type="memory.forget",
                    owner_id=clean_owner,
                    resource_id=memory_id,
                    status="success",
                    details={"verified": True},
                )
            )

        return receipt

    async def export_memories(
        self,
        owner_id: str,
        max_items: int = 1000,
    ) -> MemoryExport:
        """Export all active memories belonging to the authenticated owner.

        Applies bounded pagination to protect against memory exhaustion.
        Never crosses owner boundaries or includes deleted records.

        Args:
            owner_id: Authenticated owner ID.
            max_items: Maximum items to export in this batch (default 1000).

        Returns:
            MemoryExport container.
        """
        if not owner_id or not owner_id.strip():
            return MemoryExport(
                owner_id="",
                exported_at=utc_now(),
                total_count=0,
                items=[],
            )

        clean_owner = owner_id.strip()
        # Retrieve active items bounded by max_items
        filter_params = MemoryFilter(
            include_deleted=False,
            limit=min(max_items, 1000),
            offset=0,
        )

        items = await self.list_memories(
            owner_id=clean_owner,
            filter_params=filter_params,
        )

        return MemoryExport(
            owner_id=clean_owner,
            exported_at=utc_now(),
            total_count=len(items),
            items=items,
        )

    async def search_memories(
        self,
        owner_id: str,
        query: str | RetrievalRequest,
        top_k: int = 5,
        kind: MemoryKind | None = None,
        sensitivity: SensitivityLevel | None = None,
        approved_only: bool | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        reference_time: datetime | None = None,
    ) -> RetrievalResult:
        """Search active memories belonging to the authenticated owner.

        Args:
            owner_id: Authenticated owner ID.
            query: Query text string or a pre-built RetrievalRequest.
            top_k: Maximum ranked results to return.
            kind: Optional filter by memory kind.
            sensitivity: Optional filter by sensitivity level.
            approved_only: Optional filter for approved items only.
            occurred_after: Optional cutoff for earliest event timestamp.
            occurred_before: Optional cutoff for latest event timestamp.
            reference_time: Optional evaluation timestamp for recency decay.

        Returns:
            RetrievalResult containing ranked MemorySearchResult items.
        """
        if not owner_id or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string.")

        clean_owner = owner_id.strip()

        if isinstance(query, RetrievalRequest):
            request = query
        else:
            request = RetrievalRequest(
                query=query,
                top_k=top_k,
                kind=kind,
                sensitivity=sensitivity,
                approved_only=approved_only,
                occurred_after=occurred_after,
                occurred_before=occurred_before,
            )

        result = await self._retrieval_service.retrieve(
            owner_id=clean_owner,
            request=request,
            reference_time=reference_time,
        )

        if self._audit_logger:
            await self._audit_logger.log_event(
                AuditEvent(
                    event_type="memory.search",
                    owner_id=clean_owner,
                    resource_id=None,
                    details={
                        "returned_count": result.returned_count,
                        "total_eligible": result.total_eligible,
                    },
                )
            )

        return result
