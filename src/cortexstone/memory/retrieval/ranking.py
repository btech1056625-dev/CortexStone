"""Scoring and ranking engine for CortexStone memory retrieval.

Computes normalized composite scores combining:
- Semantic similarity (cosine similarity in range [-1.0, 1.0], normalized to [0.0, 1.0])
- Temporal recency score via exponential decay in range [0.0, 1.0]
- Confidence score in range [0.0, 1.0] (defaulting safely when missing)

Formulation:
    composite_score = (w_sem * norm_sim) + (w_rec * recency) + (w_conf * norm_conf)

Deterministic tie-breaking:
    Rank by (-composite_score, -created_at_epoch, id_str)
"""

import math
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cortexstone.db.base import utc_now


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two float vectors.

    Args:
        vec1: First vector.
        vec2: Second vector.

    Returns:
        Cosine similarity in [-1.0, 1.0]. Returns 0.0 if either vector has zero magnitude.

    Raises:
        ValueError: If vector lengths mismatch or vectors are empty.
    """
    if not vec1 or not vec2:
        raise ValueError("Vectors must not be empty.")
    if len(vec1) != len(vec2):
        raise ValueError(
            f"Vector dimension mismatch: len(vec1)={len(vec1)} != len(vec2)={len(vec2)}."
        )

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0

    sim = dot / (math.sqrt(norm1) * math.sqrt(norm2))
    # Clamp against floating point inaccuracy
    return max(-1.0, min(1.0, sim))


class RankingConfig(BaseModel):
    """Configuration weights and decay parameters for memory ranking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    semantic_weight: float = Field(
        default=0.6,
        ge=0.0,
        description="Weight assigned to normalized semantic similarity.",
    )
    recency_weight: float = Field(
        default=0.25,
        ge=0.0,
        description="Weight assigned to temporal recency score.",
    )
    confidence_weight: float = Field(
        default=0.15,
        ge=0.0,
        description="Weight assigned to confidence score.",
    )
    half_life_days: float = Field(
        default=30.0,
        gt=0.0,
        description="Half-life in days for exponential recency decay.",
    )
    default_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Default confidence assigned when memory record has confidence=None.",
    )


def compute_recency_score(
    item_timestamp: Optional[datetime],
    reference_time: Optional[datetime] = None,
    half_life_days: float = 30.0,
) -> float:
    """Compute exponential decay recency score in range [0.0, 1.0].

    Score = exp(-lambda * delta_days), where lambda = ln(2) / half_life_days.
    If item_timestamp is None, returns 0.0.
    If delta_days < 0 (future event), score is capped at 1.0.

    Args:
        item_timestamp: Timestamp of the memory item (created_at or occurred_at, UTC).
        reference_time: Current evaluation time (defaults to utc_now()).
        half_life_days: Number of days over which score halves.

    Returns:
        Float score in [0.0, 1.0].
    """
    if item_timestamp is None:
        return 0.0

    if reference_time is None:
        reference_time = utc_now()

    # Ensure timezone awareness
    if item_timestamp.tzinfo is None:
        raise ValueError("item_timestamp must be timezone-aware (UTC).")
    if reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware (UTC).")

    delta_seconds = (reference_time - item_timestamp).total_seconds()
    if delta_seconds <= 0:
        return 1.0

    delta_days = delta_seconds / 86400.0
    decay_constant = math.log(2.0) / half_life_days
    recency = math.exp(-decay_constant * delta_days)
    return max(0.0, min(1.0, recency))


def compute_composite_score(
    semantic_similarity: Optional[float],
    item_timestamp: Optional[datetime],
    confidence: Optional[float],
    config: RankingConfig,
    reference_time: Optional[datetime] = None,
) -> float:
    """Calculate the final normalized composite ranking score.

    Ranges:
    - Raw cosine similarity in [-1.0, 1.0] -> normalized to [0.0, 1.0] via (sim + 1) / 2.
    - If semantic_similarity is None, normalized similarity is treated as 0.0.
    - Recency score in [0.0, 1.0].
    - Confidence in [0.0, 1.0] (fallback to config.default_confidence).

    The total weight sum normalizes the final score to [0.0, 1.0].
    """
    total_weight = (
        config.semantic_weight + config.recency_weight + config.confidence_weight
    )
    if total_weight <= 0.0:
        return 0.0

    # 1. Normalize semantic similarity
    if semantic_similarity is not None:
        # Clamp between -1.0 and 1.0 then scale to [0.0, 1.0]
        clamped_sim = max(-1.0, min(1.0, semantic_similarity))
        norm_sim = (clamped_sim + 1.0) / 2.0
    else:
        norm_sim = 0.0

    # 2. Recency score
    recency = compute_recency_score(
        item_timestamp=item_timestamp,
        reference_time=reference_time,
        half_life_days=config.half_life_days,
    )

    # 3. Confidence score
    if confidence is not None:
        norm_conf = max(0.0, min(1.0, confidence))
    else:
        norm_conf = config.default_confidence

    raw_score = (
        (config.semantic_weight * norm_sim)
        + (config.recency_weight * recency)
        + (config.confidence_weight * norm_conf)
    )

    return raw_score / total_weight
