"""Embeddings package root.

Exports EmbeddingProvider, EmbeddingConfig, vector validation,
normalization utilities, and domain exceptions.
"""

from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.embeddings.bge import BGEEmbeddingProvider
from cortexstone.memory.embeddings.config import (
    BGE_SMALL_DIMENSION,
    BGE_SMALL_MODEL_ID,
    BGE_SMALL_QUERY_INSTRUCTION,
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
    "BGEEmbeddingProvider",
    "BGE_SMALL_MODEL_ID",
    "BGE_SMALL_DIMENSION",
    "BGE_SMALL_QUERY_INSTRUCTION",
    "EmbeddingConfig",
    "EmbeddingError",
    "EmbeddingConfigurationError",
    "EmbeddingDimensionMismatchError",
    "InvalidEmbeddingVectorError",
    "EmbeddingProviderError",
    "validate_embedding_vector",
    "normalize_embedding_vector",
]
