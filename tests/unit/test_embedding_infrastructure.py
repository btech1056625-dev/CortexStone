"""Unit tests for embedding configuration, vector validation, normalization, and exceptions."""

import pytest
from pydantic import ValidationError

from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.embeddings.config import (
    EmbeddingConfig,
    EmbeddingDimensionMismatchError,
    InvalidEmbeddingVectorError,
    normalize_embedding_vector,
    validate_embedding_vector,
)

# -----------------------------------------------------------------------------
# 1. Configuration Model Tests
# -----------------------------------------------------------------------------


def test_embedding_config_valid():
    """Verify valid EmbeddingConfig construction."""
    cfg = EmbeddingConfig(
        provider_id="nebius",
        model_id="Qwen/Qwen3-Embedding-8B",
        dimension=1024,
        request_timeout_seconds=45.0,
        batch_size=64,
    )
    assert cfg.provider_id == "nebius"
    assert cfg.model_id == "Qwen/Qwen3-Embedding-8B"
    assert cfg.dimension == 1024
    assert cfg.request_timeout_seconds == 45.0
    assert cfg.batch_size == 64


def test_embedding_config_defaults_and_validation():
    """Verify defaults and positive dimension constraint."""
    cfg = EmbeddingConfig(
        provider_id="fastembed",
        model_id="BAAI/bge-small-en-v1.5",
        dimension=384,
    )
    assert cfg.request_timeout_seconds == 30.0
    assert cfg.batch_size == 32

    # Reject non-positive dimension
    with pytest.raises(ValidationError):
        EmbeddingConfig(provider_id="test", model_id="test", dimension=0)


# -----------------------------------------------------------------------------
# 2. Vector Validation Tests
# -----------------------------------------------------------------------------


def test_validate_vector_valid():
    """Verify valid vector passes dimension validation."""
    vec = [0.1, 0.2, 0.3, 0.4]
    validate_embedding_vector(vec, expected_dimension=4)
    validate_embedding_vector(vec, expected_dimension=None)


def test_validate_vector_dimension_mismatch():
    """Verify mismatch between actual and expected dimension raises
    EmbeddingDimensionMismatchError.
    """
    vec = [0.1, 0.2]
    with pytest.raises(EmbeddingDimensionMismatchError) as exc_info:
        validate_embedding_vector(vec, expected_dimension=4)

    assert exc_info.value.expected == 4
    assert exc_info.value.actual == 2
    assert "expected declared dimension 4, got 2" in str(exc_info.value)


def test_validate_vector_empty_raises():
    """Verify empty vector raises InvalidEmbeddingVectorError."""
    with pytest.raises(InvalidEmbeddingVectorError, match="must not be empty"):
        validate_embedding_vector([])


def test_validate_vector_non_finite_raises():
    """Verify NaN and Inf values raise InvalidEmbeddingVectorError."""
    vec_nan = [0.1, float("nan"), 0.3]
    with pytest.raises(InvalidEmbeddingVectorError, match="non-finite value"):
        validate_embedding_vector(vec_nan)

    vec_inf = [0.1, float("inf"), 0.3]
    with pytest.raises(InvalidEmbeddingVectorError, match="non-finite value"):
        validate_embedding_vector(vec_inf)


# -----------------------------------------------------------------------------
# 3. Vector Normalization Tests
# -----------------------------------------------------------------------------


def test_normalize_vector_success():
    """Verify normalization produces unit-length vector."""
    vec = [3.0, 4.0]
    normed = normalize_embedding_vector(vec, expected_dimension=2)
    assert len(normed) == 2
    assert pytest.approx(normed[0], 1e-6) == 0.6
    assert pytest.approx(normed[1], 1e-6) == 0.8
    # L2 magnitude equals 1.0
    assert pytest.approx(sum(x * x for x in normed), 1e-6) == 1.0


def test_normalize_vector_already_unit_length():
    """Verify already normalized vector is returned directly."""
    vec = [1.0, 0.0]
    normed = normalize_embedding_vector(vec)
    assert normed == vec


def test_normalize_vector_zero_magnitude_raises():
    """Verify zero-magnitude vector raises InvalidEmbeddingVectorError."""
    vec = [0.0, 0.0, 0.0]
    with pytest.raises(InvalidEmbeddingVectorError, match="Cannot normalize zero-magnitude"):
        normalize_embedding_vector(vec)


# -----------------------------------------------------------------------------
# 4. Query vs Document Interface Compatibility
# -----------------------------------------------------------------------------


class MinimalDummyProvider(EmbeddingProvider):
    """Subclass implementing only required abstract methods."""

    @property
    def provider_name(self) -> str:
        return "minimal-dummy"

    @property
    def dimension(self) -> int:
        return 3

    async def embed_text(self, text: str):
        return [0.1, 0.2, 0.3]

    async def embed_batch(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.mark.anyio
async def test_query_and_document_delegation():
    """Verify embed_query and embed_document delegate cleanly to embed_text by default."""
    provider = MinimalDummyProvider()
    q_vec = await provider.embed_query("search text")
    d_vec = await provider.embed_document("memory content")

    assert q_vec == [0.1, 0.2, 0.3]
    assert d_vec == [0.1, 0.2, 0.3]
