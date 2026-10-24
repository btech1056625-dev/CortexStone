"""Unit tests for BGEEmbeddingProvider (BAAI/bge-small-en-v1.5, 384 dimensions).

Mocks model inference backends to guarantee:
1. Zero network model downloading during ordinary test execution.
2. Exact 384-dimensional vector validation and L2 normalization.
3. Batch embedding ordering and boundary validation.
4. Asymmetric retrieval prefixing on queries vs document embedding.
5. Strict rejection of empty, non-string, or non-finite inputs.
6. Clean domain error wrapping for model loading and inference failures.
7. Seamless integration with MemoryRetrievalService.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cortexstone.db.base import utc_now
from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.embeddings import (
    BGE_SMALL_DIMENSION,
    BGE_SMALL_MODEL_ID,
    BGE_SMALL_QUERY_INSTRUCTION,
    BGEEmbeddingProvider,
    EmbeddingConfig,
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
)
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.retrieval.ranking import RankingConfig
from cortexstone.memory.retrieval.retriever import MemoryRetrievalService, RetrievalRequest
from cortexstone.memory.schemas import MemoryFilter


class MockFastEmbedBackend:
    """Mock FastEmbed backend producing deterministic 384-dimensional vectors."""

    def __init__(self, dimension: int = BGE_SMALL_DIMENSION) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str], batch_size: int = 32):
        self.calls.append(list(texts))
        for text in texts:
            # Deterministic pseudo-vector seeded by text length
            seed = len(text)
            vec = [(seed + i) % 10 + 0.1 for i in range(self.dimension)]
            yield vec


# -----------------------------------------------------------------------------
# 1. Initialization and Configuration Tests
# -----------------------------------------------------------------------------


def test_bge_provider_default_initialization():
    """Verify BGEEmbeddingProvider defaults to BAAI/bge-small-en-v1.5 with 384 dimensions."""
    provider = BGEEmbeddingProvider()
    assert provider.dimension == 384
    assert provider.model_id == "BAAI/bge-small-en-v1.5"
    assert provider.provider_name == "fastembed:BAAI/bge-small-en-v1.5"
    assert provider.query_instruction == BGE_SMALL_QUERY_INSTRUCTION


def test_bge_provider_rejects_incompatible_dimension():
    """Verify provider rejects configuration if dimension is not 384."""
    bad_config = EmbeddingConfig(
        provider_id="fastembed",
        model_id=BGE_SMALL_MODEL_ID,
        dimension=512,  # BGE-small is strictly 384
    )
    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        BGEEmbeddingProvider(config=bad_config)

    assert exc_info.value.expected == 384
    assert exc_info.value.actual == 512


# -----------------------------------------------------------------------------
# 2. Embedding Generation and Output Dimensions Tests
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bge_embed_text_output_dimension_and_normalization():
    """Verify single text embedding produces normalized 384-d vector."""
    mock_backend = MockFastEmbedBackend()
    provider = BGEEmbeddingProvider(model=mock_backend)

    vector = await provider.embed_text("CortexStone security memory subsystem")

    assert len(vector) == 384
    # Verify L2 normalization: sum(x^2) == 1.0 within floating tolerance
    magnitude = sum(x * x for x in vector)
    assert pytest.approx(magnitude, rel=1e-5) == 1.0


@pytest.mark.anyio
async def test_bge_embed_batch_preserves_order_and_handles_multiple():
    """Verify batch embedding preserves input order and returns expected count."""
    mock_backend = MockFastEmbedBackend()
    provider = BGEEmbeddingProvider(model=mock_backend)

    inputs = ["Document alpha", "Document beta", "Document gamma"]
    vectors = await provider.embed_batch(inputs)

    assert len(vectors) == 3
    for vec in vectors:
        assert len(vec) == 384
        assert pytest.approx(sum(x * x for x in vec), rel=1e-5) == 1.0

    # Ensure backend received the cleaned texts
    assert mock_backend.calls == [inputs]


@pytest.mark.anyio
async def test_bge_query_vs_document_prefixing():
    """Verify embed_query applies BGE prefix instruction while embed_document does not."""
    mock_backend = MockFastEmbedBackend()
    provider = BGEEmbeddingProvider(model=mock_backend)

    # 1. Query embedding
    query_text = "What is Apurva's deployment schedule?"
    await provider.embed_query(query_text)

    expected_prefixed = f"{BGE_SMALL_QUERY_INSTRUCTION}{query_text}"
    assert mock_backend.calls[0] == [expected_prefixed]

    # 2. Document embedding
    doc_text = "Apurva deploys on Tuesday mornings."
    await provider.embed_document(doc_text)
    assert mock_backend.calls[1] == [doc_text]


# -----------------------------------------------------------------------------
# 3. Invalid Input Handling Tests
# -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bge_embed_text_invalid_inputs_raise():
    """Verify empty or non-string inputs to embed_text raise ValueError."""
    mock_backend = MockFastEmbedBackend()
    provider = BGEEmbeddingProvider(model=mock_backend)

    with pytest.raises(ValueError, match="must be a string"):
        await provider.embed_text(None)  # type: ignore

    with pytest.raises(ValueError, match="must not be empty or blank"):
        await provider.embed_text("")

    with pytest.raises(ValueError, match="must not be empty or blank"):
        await provider.embed_text("   \n\t  ")


@pytest.mark.anyio
async def test_bge_embed_batch_invalid_inputs_raise():
    """Verify invalid batch lists raise ValueError."""
    mock_backend = MockFastEmbedBackend()
    provider = BGEEmbeddingProvider(model=mock_backend)

    with pytest.raises(ValueError, match="must be a list or tuple"):
        await provider.embed_batch("not a list")  # type: ignore

    with pytest.raises(ValueError, match="must not be empty"):
        await provider.embed_batch([])

    with pytest.raises(ValueError, match="must not be empty or blank"):
        await provider.embed_batch(["valid", "   "])

    with pytest.raises(ValueError, match="must be a string"):
        await provider.embed_batch(["valid", 123])  # type: ignore


# -----------------------------------------------------------------------------
# 4. Model-Loading and Inference Failure Tests
# -----------------------------------------------------------------------------


def test_bge_missing_backend_package_raises_descriptive_error():
    """Verify missing fastembed package raises EmbeddingProviderError with instructions."""
    provider = BGEEmbeddingProvider()

    with patch.dict("sys.modules", {"fastembed": None}):
        with pytest.raises(EmbeddingProviderError) as exc_info:
            provider._get_model()

    assert "package is required" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


@pytest.mark.anyio
async def test_bge_dimension_mismatch_from_backend_raises():
    """Verify backend producing non-384 dimensional output raises EmbeddingProviderError."""
    # Mock backend producing 512 dimensions instead of 384
    bad_backend = MockFastEmbedBackend(dimension=512)
    provider = BGEEmbeddingProvider(model=bad_backend)

    with pytest.raises(EmbeddingProviderError, match="Vector validation/normalization failed"):
        await provider.embed_text("test content")


@pytest.mark.anyio
async def test_bge_non_finite_values_raise():
    """Verify backend producing NaN or Inf raises EmbeddingProviderError."""
    bad_backend = MagicMock()
    bad_backend.embed.return_value = [[float("nan")] * 384]
    provider = BGEEmbeddingProvider(model=bad_backend)

    with pytest.raises(EmbeddingProviderError, match="Vector validation/normalization failed"):
        await provider.embed_text("test content")


# -----------------------------------------------------------------------------
# 5. Integration with MemoryRetrievalService
# -----------------------------------------------------------------------------


class MockMemoryRepository(MemoryRepositoryInterface):
    """In-memory repository returning pre-configured test models."""

    def __init__(self, items: list[MemoryItemModel]) -> None:
        self.items = items

    async def create(self, owner_id, item):
        raise NotImplementedError

    async def get_by_id(self, owner_id, memory_id, include_deleted=False):
        raise NotImplementedError

    async def list(self, owner_id: str, filter_params: MemoryFilter | None = None):
        return [m for m in self.items if m.owner_id == owner_id and m.deleted_at is None]

    async def update(self, owner_id, memory_id, update_data, allow_approval_change=False):
        raise NotImplementedError

    async def soft_delete(self, owner_id, memory_id):
        raise NotImplementedError

    async def hard_delete(self, owner_id, memory_id):
        raise NotImplementedError

    async def search_semantic(self, owner_id, query_vector, top_k=5, filter_params=None):
        raise NotImplementedError


@pytest.mark.anyio
async def test_bge_provider_retrieval_service_integration():
    """Verify BGEEmbeddingProvider seamlessly integrates with MemoryRetrievalService."""
    # 1. Setup mock backend and BGE provider
    mock_backend = MockFastEmbedBackend(dimension=384)
    provider = BGEEmbeddingProvider(model=mock_backend)

    # 2. Setup candidate item with valid 384-dimensional embedding
    dummy_vec = [1.0 / (384**0.5)] * 384
    now = utc_now()
    item = MemoryItemModel(
        id=uuid4(),
        owner_id="user_apurva",
        kind="fact",
        title="BGE Integration",
        content="CortexStone uses BAAI/bge-small-en-v1.5 with 384 dimensions.",
        embedding=dummy_vec,
        confidence=0.95,
        sensitivity="normal",
        approved=True,
        metadata_={"is_inferred": False},
        created_at=now,
        updated_at=now,
    )
    repo = MockMemoryRepository([item])

    # 3. Initialize MemoryRetrievalService with BGE provider
    retrieval_service = MemoryRetrievalService(
        repository=repo,
        embedding_provider=provider,
        ranking_config=RankingConfig(),
    )

    # 4. Execute retrieval
    req = RetrievalRequest(query="Which embedding model does CortexStone use?", top_k=5)
    result = await retrieval_service.retrieve(owner_id="user_apurva", request=req)

    assert result.returned_count == 1
    assert result.items[0].item.title == "BGE Integration"
    assert result.items[0].relevance_score > 0.0
    assert result.items[0].semantic_distance is not None
