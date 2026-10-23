"""Retrieval service and pipeline for CortexStone memory.

Executes owner-scoped memory retrieval combining:
1. Owner scoping and deleted_at IS NULL filtering at repository level.
2. Query embedding generation with dimension validation against an injected EmbeddingProvider.
3. Filtering by kind, sensitivity, approval, and temporal bounds.
4. Composite ranking across semantic similarity, recency decay, and confidence.
5. Deterministic tie-breaking and bounded top-k return sets.
6. Provenance and uncertainty preservation.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cortexstone.db.base import utc_now
from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.embeddings.config import (
    EmbeddingConfigurationError,
    validate_embedding_vector,
)
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.retrieval.ranking import (
    RankingConfig,
    compute_composite_score,
    cosine_similarity,
)
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemRead,
    MemoryKind,
    MemorySearchResult,
    SensitivityLevel,
)


class RetrievalRequest(BaseModel):
    """Specification of a memory retrieval query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        description="Search query text. Must not be empty or blank.",
    )

    @field_validator("query")
    @classmethod
    def validate_query_non_empty(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Query text must not be blank or whitespace-only.")
        return trimmed

    kind: MemoryKind | None = Field(
        default=None,
        description="Filter by specific memory kind ('fact', 'episode', 'skill').",
    )
    sensitivity: SensitivityLevel | None = Field(
        default=None,
        description="Filter by sensitivity tier.",
    )
    approved_only: bool | None = Field(
        default=None,
        description="Filter for approved items (essential for skills).",
    )
    occurred_after: datetime | None = Field(
        default=None,
        description="Filter events occurred on or after this UTC timestamp.",
    )
    occurred_before: datetime | None = Field(
        default=None,
        description="Filter events occurred on or before this UTC timestamp.",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of ranked results to return.",
    )


class RetrievalResult(BaseModel):
    """Container for retrieval results with query metadata."""

    model_config = ConfigDict(frozen=True)

    owner_id: str
    query: str
    total_eligible: int
    returned_count: int
    items: list[MemorySearchResult]


class MemoryRetrieverInterface(ABC):
    """Abstract interface for memory retrieval."""

    @abstractmethod
    async def retrieve(
        self,
        owner_id: str,
        request: RetrievalRequest,
        reference_time: datetime | None = None,
    ) -> RetrievalResult:
        """Execute owner-scoped memory retrieval.

        Args:
            owner_id: Authenticated owner ID.
            request: Validated RetrievalRequest specification.
            reference_time: Optional evaluation time for recency scoring.

        Returns:
            RetrievalResult containing ranked MemorySearchResult items.
        """
        raise NotImplementedError


class MemoryRetrievalService(MemoryRetrieverInterface):
    """Pipeline orchestrating embedding generation, candidate fetch, and composite ranking.

    Architectural Boundary & In-Memory Ranking Note:
    At the current stage, the team has not yet frozen the pgvector dimension integer.
    Therefore, candidate items are retrieved through the repository's owner-scoped,
    active-record filters (WHERE owner_id = :owner AND deleted_at IS NULL), and
    similarity re-ranking is computed cleanly in-memory against candidates with embeddings.
    Once a concrete vector dimension is established, exact/HNSW vector ordering will be
    pushed down directly to SQL queries.
    """

    def __init__(
        self,
        repository: MemoryRepositoryInterface,
        embedding_provider: EmbeddingProvider | None = None,
        ranking_config: RankingConfig | None = None,
    ) -> None:
        """Initialize the retrieval service.

        Args:
            repository: Conforming MemoryRepositoryInterface instance.
            embedding_provider: Optional EmbeddingProvider. If None, semantic embedding
                                cannot be performed and an error is raised on retrieve.
            ranking_config: Optional ranking weights and half-life parameters.
        """
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._ranking_config = ranking_config or RankingConfig()

    async def retrieve(
        self,
        owner_id: str,
        request: RetrievalRequest,
        reference_time: datetime | None = None,
    ) -> RetrievalResult:
        """Retrieve, rank, and return top-k memory items for the authenticated owner."""
        # 1. Validate owner_id
        if not owner_id or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string.")
        clean_owner = owner_id.strip()

        # 2. Validate query text
        clean_query = request.query.strip()
        if not clean_query:
            raise ValueError("Query text must not be empty or blank.")

        # 3. Require configured embedding provider
        if self._embedding_provider is None:
            raise EmbeddingConfigurationError(
                "EmbeddingProvider is not configured on MemoryRetrievalService. "
                "Semantic retrieval cannot be performed."
            )

        # 4. Generate query embedding using query semantics & validate vector
        query_vector = await self._embedding_provider.embed_query(clean_query)
        expected_dim = self._embedding_provider.dimension
        validate_embedding_vector(query_vector, expected_dimension=expected_dim)

        # 5. Fetch eligible candidate records strictly scoped to owner
        # Candidate pool limit is bounded to protect memory
        candidate_filter = MemoryFilter(
            kind=request.kind,
            sensitivity=request.sensitivity,
            approved_only=request.approved_only,
            occurred_after=request.occurred_after,
            occurred_before=request.occurred_before,
            include_deleted=False,  # CRITICAL: Always exclude soft-deleted items
            limit=100,  # Bounded candidate pool for re-ranking
            offset=0,
        )

        candidate_models = await self._repository.list(
            owner_id=clean_owner,
            filter_params=candidate_filter,
        )

        if reference_time is None:
            reference_time = utc_now()

        # 6. Score each candidate
        scored_candidates: list[tuple[float, MemoryItemModel, float | None]] = []

        for model in candidate_models:
            # Defensive check: ensure no soft-deleted record slipped through
            if model.deleted_at is not None:
                continue

            # Defensive check: ensure owner_id matches
            if model.owner_id != clean_owner:
                continue

            # Compute semantic similarity if item has stored embedding
            sem_sim: float | None = None
            if model.embedding is not None:
                try:
                    # model.embedding may be a list or vector
                    item_vector = model.embedding
                    if isinstance(item_vector, (list, tuple)) and len(item_vector) == expected_dim:
                        sem_sim = cosine_similarity(query_vector, list(item_vector))
                except Exception:
                    sem_sim = None

            # Calculate composite score
            # Prioritize occurred_at for timeline events, fallback to created_at
            item_time = model.occurred_at or model.created_at
            score = compute_composite_score(
                semantic_similarity=sem_sim,
                item_timestamp=item_time,
                confidence=model.confidence,
                config=self._ranking_config,
                reference_time=reference_time,
            )
            scored_candidates.append((score, model, sem_sim))

        # 7. Deterministic tie-breaking sort:
        # Highest score first (-score), then most recent created_at (-epoch), then id string
        def sort_key(entry):
            score, model, _ = entry
            created_epoch = model.created_at.timestamp() if model.created_at else 0.0
            return (-score, -created_epoch, str(model.id))

        scored_candidates.sort(key=sort_key)

        # 8. Slice top_k
        top_candidates = scored_candidates[: request.top_k]

        # 9. Format into domain MemorySearchResult items
        search_results: list[MemorySearchResult] = []
        for score, model, sem_sim in top_candidates:
            read_item = MemoryItemRead.model_validate(model)
            search_results.append(
                MemorySearchResult(
                    item=read_item,
                    relevance_score=round(score, 4),
                    semantic_distance=round(1.0 - sem_sim, 4) if sem_sim is not None else None,
                )
            )

        return RetrievalResult(
            owner_id=clean_owner,
            query=clean_query,
            total_eligible=len(candidate_models),
            returned_count=len(search_results),
            items=search_results,
        )
