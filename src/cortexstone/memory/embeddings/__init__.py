"""Embeddings package root.

Exports EmbeddingProvider, EmbeddingConfig, vector validation,
normalization utilities, and domain exceptions.
"""

from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.embeddings.config import (
    EmbeddingConfig,
    EmbeddingConfigurationError,
    EmbeddingDimensionMismatchError,
    EmbeddingError,
    EmbeddingProviderError,
    InvalidEmbeddingVectorError,
    normalize_embedding_vector,
    validate_embedding_vector,
)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingConfig",
    "EmbeddingError",
    "EmbeddingConfigurationError",
    "EmbeddingDimensionMismatchError",
    "InvalidEmbeddingVectorError",
    "EmbeddingProviderError",
    "validate_embedding_vector",
    "normalize_embedding_vector",
]
