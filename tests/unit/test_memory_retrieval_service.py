"""Unit tests for MemoryRetrievalService pipeline, validation, and filters."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.retrieval.retriever import (
    MemoryRetrievalService,
    RetrievalRequest,
    RetrievalResult,
)
from cortexstone.memory.retrieval.ranking import RankingConfig
from cortexstone.memory.schemas import MemoryKind, SensitivityLevel, utc_now


class FakeDeterministicEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider for tests."""

    def __init__(self, dimension: int = 4, fixed_vector=None) -> None:
        self._dim = dimension
        self._fixed = fixed_vector

    @property
    def provider_name(self) -> str:
        return "fake-deterministic"

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_text(self, text: str):
        if self._fixed is not None:
            return self._fixed
        # Generate predictable normalized vector based on length
        return [1.0 / (self._dim ** 0.5)] * self._dim

    async def embed_batch(self, texts):
        return [await self.embed_text(t) for t in texts]


def make_candidate_model(
    owner_id: str,
    content: str,
    memory_id=None,
    kind="fact",
    embedding=None,
    confidence=0.9,
    approved=False,
    deleted_at=None,
    occurred_at=None,
    created_at=None,
) -> MemoryItemModel:
    return MemoryItemModel(
        id=memory_id or uuid4(),
        owner_id=owner_id,
        kind=kind,
        content=content,
        embedding=embedding,
        confidence=confidence,
        approved=approved,
        deleted_at=deleted_at,
        occurred_at=occurred_at,
        sensitivity="normal",
        metadata_={"is_inferred": False},
        created_at=created_at or utc_now(),
        updated_at=utc_now(),
    )


# -----------------------------------------------------------------------------
# 1. Pipeline Validation Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_retrieve_missing_provider_raises_error():
    """Verify retrieval raises explicit RuntimeError if no EmbeddingProvider is configured."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=None)

    req = RetrievalRequest(query="user preferences")
    with pytest.raises(RuntimeError, match="EmbeddingProvider is not configured"):
        await service.retrieve(owner_id="user_1", request=req)


@pytest.mark.anyio
async def test_retrieve_empty_owner_id_raises():
    """Verify empty or whitespace owner_id raises ValueError."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    provider = FakeDeterministicEmbeddingProvider()
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=provider)

    req = RetrievalRequest(query="find something")
    with pytest.raises(ValueError, match="owner_id must be a non-empty string"):
        await service.retrieve(owner_id="   ", request=req)


@pytest.mark.anyio
async def test_retrieve_empty_query_raises():
    """Verify empty or whitespace query is rejected by Pydantic schema or service."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    provider = FakeDeterministicEmbeddingProvider()
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=provider)

    with pytest.raises(Exception):
        RetrievalRequest(query="   ")


@pytest.mark.anyio
async def test_retrieve_dimension_mismatch_raises():
    """Verify mismatch between declared dimension and vector length raises ValueError."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    # Declares dimension 4, but returns vector of length 2
    bad_provider = FakeDeterministicEmbeddingProvider(dimension=4, fixed_vector=[1.0, 0.0])
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=bad_provider)

    req = RetrievalRequest(query="search")
    with pytest.raises(ValueError, match="expected declared dimension 4"):
        await service.retrieve(owner_id="user_1", request=req)


# -----------------------------------------------------------------------------
# 2. Owner Scoping, Deletion Exclusion, and Filter Delegation
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_retrieve_propagates_owner_id_and_filters():
    """Verify candidate listing is strictly scoped to owner_id and includes filters."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    mock_repo.list.return_value = []
    provider = FakeDeterministicEmbeddingProvider(dimension=4)
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=provider)

    req = RetrievalRequest(
        query="python",
        kind=MemoryKind.FACT,
        approved_only=True,
        top_k=3,
    )

    result = await service.retrieve(owner_id="user_owner_a", request=req)
    assert result.owner_id == "user_owner_a"
    assert result.returned_count == 0

    # Inspect call to repository
    call_kwargs = mock_repo.list.call_args[1]
    assert call_kwargs["owner_id"] == "user_owner_a"
    filter_arg = call_kwargs["filter_params"]
    assert filter_arg.kind == MemoryKind.FACT
    assert filter_arg.approved_only is True
    assert filter_arg.include_deleted is False


@pytest.mark.anyio
async def test_retrieve_defensively_excludes_deleted_and_other_owners():
    """Verify deleted records and mismatched owners are discarded even if returned by repo."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    provider = FakeDeterministicEmbeddingProvider(dimension=2, fixed_vector=[1.0, 0.0])

    m_valid = make_candidate_model(owner_id="user_target", content="Valid memory", embedding=[1.0, 0.0])
    m_deleted = make_candidate_model(
        owner_id="user_target",
        content="Deleted memory",
        embedding=[1.0, 0.0],
        deleted_at=utc_now(),
    )
    m_other_user = make_candidate_model(
        owner_id="user_attacker",
        content="Attacker memory",
        embedding=[1.0, 0.0],
    )

    mock_repo.list.return_value = [m_valid, m_deleted, m_other_user]
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=provider)

    req = RetrievalRequest(query="test", top_k=5)
    res = await service.retrieve(owner_id="user_target", request=req)

    # Only m_valid should survive
    assert res.returned_count == 1
    assert res.items[0].item.id == m_valid.id
    assert res.items[0].item.content == "Valid memory"


# -----------------------------------------------------------------------------
# 3. Ranking, Bounded Top-K, and Deterministic Tie-Breaking
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_retrieve_bounded_top_k_and_ranking_order():
    """Verify top-k bounding and that closer semantic vectors rank higher."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    # Query vector is [1.0, 0.0]
    provider = FakeDeterministicEmbeddingProvider(dimension=2, fixed_vector=[1.0, 0.0])

    now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)

    # Candidate 1: Identical vector [1.0, 0.0] -> sim = 1.0
    m_high = make_candidate_model(
        owner_id="u1",
        content="High match",
        embedding=[1.0, 0.0],
        confidence=1.0,
        created_at=now,
    )
    # Candidate 2: Orthogonal vector [0.0, 1.0] -> sim = 0.0
    m_med = make_candidate_model(
        owner_id="u1",
        content="Medium match",
        embedding=[0.0, 1.0],
        confidence=1.0,
        created_at=now,
    )
    # Candidate 3: Opposite vector [-1.0, 0.0] -> sim = -1.0
    m_low = make_candidate_model(
        owner_id="u1",
        content="Low match",
        embedding=[-1.0, 0.0],
        confidence=1.0,
        created_at=now,
    )

    mock_repo.list.return_value = [m_med, m_low, m_high]
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=provider)

    req = RetrievalRequest(query="search", top_k=2)
    res = await service.retrieve(owner_id="u1", request=req, reference_time=now)

    assert res.returned_count == 2
    # First item must be m_high
    assert res.items[0].item.id == m_high.id
    assert res.items[0].relevance_score > res.items[1].relevance_score
    # Second item must be m_med
    assert res.items[1].item.id == m_med.id


@pytest.mark.anyio
async def test_retrieve_deterministic_tie_breaking():
    """Verify identical scores tie-break deterministically by created_at DESC then id."""
    mock_repo = AsyncMock(spec=MemoryRepositoryInterface)
    provider = FakeDeterministicEmbeddingProvider(dimension=2, fixed_vector=[1.0, 0.0])

    t_earlier = datetime(2026, 10, 21, 10, 0, 0, tzinfo=timezone.utc)
    t_later = datetime(2026, 10, 21, 11, 0, 0, tzinfo=timezone.utc)

    m1 = make_candidate_model(owner_id="u1", content="Earlier", embedding=[1.0, 0.0], created_at=t_earlier)
    m2 = make_candidate_model(owner_id="u1", content="Later", embedding=[1.0, 0.0], created_at=t_later)

    mock_repo.list.return_value = [m1, m2]
    # Set weights to only test recency/tie-break
    config = RankingConfig(semantic_weight=1.0, recency_weight=0.0, confidence_weight=0.0)
    service = MemoryRetrievalService(repository=mock_repo, embedding_provider=provider, ranking_config=config)

    req = RetrievalRequest(query="test", top_k=2)
    res = await service.retrieve(owner_id="u1", request=req)

    assert res.returned_count == 2
    # Both have identical semantic score (1.0), so tie-break should pick m2 (more recent)
    assert res.items[0].item.id == m2.id
    assert res.items[1].item.id == m1.id
