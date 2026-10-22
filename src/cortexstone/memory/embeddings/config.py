"""Typed configuration, domain exceptions, and vector validation/normalization utilities.

Provides provider-neutral validation and normalization for embedding vectors
without freezing a specific model ID or dimension integer.
"""

import math
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------
# 1. Domain Exceptions for Embedding Operations
# -----------------------------------------------------------------------------

class EmbeddingError(Exception):
    """Base exception for all embedding-related errors.

    Ensures raw memory contents, secrets, or API keys are never embedded in error messages.
    """


class EmbeddingConfigurationError(EmbeddingError, RuntimeError):
    """Raised when an embedding provider or configuration is invalid or missing."""


class EmbeddingDimensionMismatchError(EmbeddingError, ValueError):
    """Raised when a vector dimension does not match the expected/configured dimension."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"Embedding dimension mismatch: expected declared dimension {expected}, got {actual}."
        )
        self.expected = expected
        self.actual = actual


class InvalidEmbeddingVectorError(EmbeddingError, ValueError):
    """Raised when an embedding vector is empty, contains non-finite values (NaN/inf), or zero magnitude."""


class EmbeddingProviderError(EmbeddingError, RuntimeError):
    """Raised when an external or local embedding provider fails during inference."""


# -----------------------------------------------------------------------------
# 2. Provider-Independent Configuration Abstraction
# -----------------------------------------------------------------------------

class EmbeddingConfig(BaseModel):
    """Typed configuration for an embedding provider.

    Does not hardcode an unapproved model or dimension. Values must be provided
    via environment/application configuration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the provider (e.g., 'nebius', 'fastembed', 'fake').",
    )
    model_id: str = Field(
        ...,
        min_length=1,
        description="Exact model identifier (e.g., 'Qwen/Qwen3-Embedding-8B', 'BAAI/bge-small-en-v1.5').",
    )
    dimension: int = Field(
        ...,
        gt=0,
        description="Expected embedding vector dimension (e.g., 384, 768, 1024, 1536).",
    )
    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Timeout for embedding generation calls.",
    )
    batch_size: int = Field(
        default=32,
        gt=0,
        le=512,
        description="Maximum batch size for vector generation.",
    )


# -----------------------------------------------------------------------------
# 3. Vector Validation and Normalization Utilities
# -----------------------------------------------------------------------------

def validate_embedding_vector(
    vector: List[float],
    expected_dimension: Optional[int] = None,
) -> None:
    """Validate an embedding vector's dimension and numerical integrity.

    Rejects:
    - Non-list or empty vectors.
    - Vectors whose length does not match expected_dimension (if provided).
    - Vectors containing non-finite values (NaN, positive or negative infinity).

    Does NOT log or include the vector contents or sensitive context in error messages.

    Args:
        vector: List of floating-point numbers.
        expected_dimension: Optional expected dimensionality integer.

    Raises:
        InvalidEmbeddingVectorError: If vector is empty or contains non-finite numbers.
        EmbeddingDimensionMismatchError: If vector length does not match expected_dimension.
    """
    if not isinstance(vector, (list, tuple)) or len(vector) == 0:
        raise InvalidEmbeddingVectorError("Embedding vector must not be empty.")

    actual_dim = len(vector)
    if expected_dimension is not None and actual_dim != expected_dimension:
        raise EmbeddingDimensionMismatchError(
            expected=expected_dimension,
            actual=actual_dim,
        )

    for idx, val in enumerate(vector):
        if not isinstance(val, (int, float)) or not math.isfinite(val):
            raise InvalidEmbeddingVectorError(
                f"Embedding vector contains non-finite value at index {idx}."
            )


def normalize_embedding_vector(
    vector: List[float],
    expected_dimension: Optional[int] = None,
) -> List[float]:
    """Produce a unit-length (L2-normalized) embedding vector.

    Validates:
    - Non-empty vector.
    - Finite numerical values.
    - Dimensionality matches expected_dimension if provided.
    - Non-zero vector magnitude (zero magnitude vectors cannot be normalized to unit length).

    Args:
        vector: Input float vector.
        expected_dimension: Optional expected dimensionality.

    Returns:
        New List[float] representing unit-length vector with sum(x^2) == 1.0.

    Raises:
        InvalidEmbeddingVectorError: If vector is empty, non-finite, or has zero magnitude.
        EmbeddingDimensionMismatchError: If dimension does not match.
    """
    validate_embedding_vector(vector, expected_dimension=expected_dimension)

    sum_sq = sum(x * x for x in vector)
    norm = math.sqrt(sum_sq)

    if norm == 0.0 or not math.isfinite(norm):
        raise InvalidEmbeddingVectorError(
            "Cannot normalize zero-magnitude or non-finite vector to unit length."
        )

    # Avoid re-normalizing if already within floating-point tolerance of unit length
    if abs(norm - 1.0) < 1e-6:
        return list(vector)

    return [x / norm for x in vector]
