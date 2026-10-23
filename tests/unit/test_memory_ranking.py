"""Unit tests for memory retrieval ranking formulas and scoring logic."""

from datetime import UTC, datetime, timedelta

import pytest

from cortexstone.memory.retrieval.ranking import (
    RankingConfig,
    compute_composite_score,
    compute_recency_score,
    cosine_similarity,
)


def test_cosine_similarity_identical_vectors():
    """Verify cosine similarity of identical vectors is 1.0."""
    v1 = [1.0, 2.0, 3.0]
    sim = cosine_similarity(v1, v1)
    assert pytest.approx(sim, 1e-6) == 1.0


def test_cosine_similarity_orthogonal_vectors():
    """Verify cosine similarity of orthogonal vectors is 0.0."""
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    sim = cosine_similarity(v1, v2)
    assert pytest.approx(sim, 1e-6) == 0.0


def test_cosine_similarity_opposite_vectors():
    """Verify cosine similarity of opposite vectors is -1.0."""
    v1 = [1.0, 0.0]
    v2 = [-1.0, 0.0]
    sim = cosine_similarity(v1, v2)
    assert pytest.approx(sim, 1e-6) == -1.0


def test_cosine_similarity_dimension_mismatch_raises():
    """Verify ValueError is raised if vector dimensions differ."""
    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


def test_cosine_similarity_empty_vectors_raises():
    """Verify ValueError is raised on empty vectors."""
    with pytest.raises(ValueError, match="must not be empty"):
        cosine_similarity([], [])


def test_compute_recency_score_exact_now():
    """Verify recency score at delta=0 is 1.0."""
    now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
    score = compute_recency_score(item_timestamp=now, reference_time=now, half_life_days=30.0)
    assert pytest.approx(score, 1e-6) == 1.0


def test_compute_recency_score_half_life():
    """Verify recency score after exactly 30 days equals 0.5."""
    now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
    t_past = now - timedelta(days=30)
    score = compute_recency_score(item_timestamp=t_past, reference_time=now, half_life_days=30.0)
    assert pytest.approx(score, 1e-6) == 0.5


def test_compute_recency_score_missing_timestamp():
    """Verify recency score is 0.0 if timestamp is None."""
    score = compute_recency_score(item_timestamp=None)
    assert score == 0.0


def test_compute_recency_score_naive_datetime_raises():
    """Verify ValueError is raised if timestamp is not timezone-aware."""
    naive_dt = datetime(2026, 10, 21, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_recency_score(item_timestamp=naive_dt)


def test_compute_composite_score_normalization():
    """Verify composite score is strictly normalized between [0.0, 1.0]."""
    config = RankingConfig(
        semantic_weight=0.6,
        recency_weight=0.25,
        confidence_weight=0.15,
        half_life_days=30.0,
        default_confidence=0.5,
    )
    now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)

    # Maximum possible score: sim=1.0, recency=1.0, confidence=1.0 -> 1.0
    max_score = compute_composite_score(
        semantic_similarity=1.0,
        item_timestamp=now,
        confidence=1.0,
        config=config,
        reference_time=now,
    )
    assert pytest.approx(max_score, 1e-5) == 1.0

    # Minimum possible score: sim=-1.0 (norm_sim=0.0), no timestamp (recency=0.0),
    # confidence=0.0 -> 0.0
    min_score = compute_composite_score(
        semantic_similarity=-1.0,
        item_timestamp=None,
        confidence=0.0,
        config=config,
        reference_time=now,
    )
    assert pytest.approx(min_score, 1e-5) == 0.0


def test_compute_composite_score_missing_confidence_fallback():
    """Verify missing confidence falls back to config.default_confidence."""
    config = RankingConfig(
        semantic_weight=0.0,
        recency_weight=0.0,
        confidence_weight=1.0,
        default_confidence=0.75,
    )
    score = compute_composite_score(
        semantic_similarity=None,
        item_timestamp=None,
        confidence=None,
        config=config,
    )
    assert pytest.approx(score, 1e-5) == 0.75
