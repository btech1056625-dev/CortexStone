"""Memory retrieval package root.

Exports ranking functions, configuration, retrieval request/result models,
retrieval pipeline service, and prompt context formatters.
"""

from cortexstone.memory.retrieval.evaluation import (
    BenchmarkSummary,
    DeterministicLexicalEmbeddingProvider,
    InMemoryMemoryRepository,
    MemoryRecallBenchmarkHarness,
    QuestionEvaluationResult,
)
from cortexstone.memory.retrieval.formatter import (
    format_memory_context,
    format_memory_item_citation,
)
from cortexstone.memory.retrieval.ranking import (
    RankingConfig,
    compute_composite_score,
    compute_recency_score,
    cosine_similarity,
)
from cortexstone.memory.retrieval.retriever import (
    MemoryRetrievalService,
    MemoryRetrieverInterface,
    RetrievalRequest,
    RetrievalResult,
)

__all__ = [
    "RankingConfig",
    "compute_composite_score",
    "compute_recency_score",
    "cosine_similarity",
    "MemoryRetrievalService",
    "MemoryRetrieverInterface",
    "RetrievalRequest",
    "RetrievalResult",
    "format_memory_context",
    "format_memory_item_citation",
    "BenchmarkSummary",
    "DeterministicLexicalEmbeddingProvider",
    "InMemoryMemoryRepository",
    "MemoryRecallBenchmarkHarness",
    "QuestionEvaluationResult",
]
