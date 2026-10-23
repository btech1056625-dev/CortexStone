"""Unit tests for offline memory evaluation harness.

Verifies:
1. DeterministicLexicalEmbeddingProvider vector properties, normalization, and semantic overlap.
2. InMemoryMemoryRepository owner scoping and soft-deletion exclusion.
3. Fixture loading and seed memory hydration.
4. End-to-end 20-question memory recall benchmark execution and threshold compliance (>= 85%).
5. Tenant isolation, deleted-record filtering, citation precision, and inference distinction.
"""

import math

import pytest

from cortexstone.memory.retrieval.evaluation import (
    BenchmarkSummary,
    DeterministicLexicalEmbeddingProvider,
    InMemoryMemoryRepository,
    MemoryRecallBenchmarkHarness,
)
from cortexstone.memory.retrieval.ranking import cosine_similarity
from cortexstone.memory.schemas import (
    MemoryItemCreate,
    MemoryKind,
    SensitivityLevel,
)


@pytest.mark.anyio
async def test_deterministic_lexical_embedding_provider_properties():
    """Verify lexical embedding normalization, dimensions, and similarity behavior."""
    provider = DeterministicLexicalEmbeddingProvider(dimension=128)
    assert provider.provider_name == "deterministic-lexical-offline"
    assert provider.dimension == 128

    vec1 = await provider.embed_text("Apurva prefers Python 3.14 and Rust for backend development.")
    assert len(vec1) == 128
    # Assert unit norm (L2)
    norm = math.sqrt(sum(x * x for x in vec1))
    assert pytest.approx(norm, rel=1e-4) == 1.0

    # Test query embedding
    q_vec = await provider.embed_query("Which programming languages does Apurva prefer?")
    sim = cosine_similarity(vec1, q_vec)
    assert sim > 0.40, f"Expected high lexical similarity, got {sim}"

    # Disjoint query
    unrelated_vec = await provider.embed_query("What flights were booked to Tokyo in December?")
    unrelated_sim = cosine_similarity(vec1, unrelated_vec)
    assert unrelated_sim < 0.20, f"Expected low similarity for unrelated text, got {unrelated_sim}"

    # Batch embedding
    batch = await provider.embed_batch(["alpha", "beta"])
    assert len(batch) == 2
    assert len(batch[0]) == 128


@pytest.mark.anyio
async def test_in_memory_repository_owner_scoping_and_soft_delete():
    """Verify InMemoryMemoryRepository isolates tenants and honors soft deletion."""
    repo = InMemoryMemoryRepository()
    owner_a = "user_alpha"
    owner_b = "user_beta"

    # Create memory for Owner A
    create_payload = MemoryItemCreate(
        kind=MemoryKind.FACT,
        title="Project Name",
        content="Project is CortexStone",
        source_type="user_direct",
        source_ref="init",
        sensitivity=SensitivityLevel.NORMAL,
    )
    model_a = await repo.create(owner_id=owner_a, item=create_payload)
    assert model_a.owner_id == owner_a

    # Owner B cannot get Owner A's memory
    assert await repo.get_by_id(owner_id=owner_b, memory_id=model_a.id) is None

    # Owner A can list memories
    items_a = await repo.list(owner_id=owner_a)
    assert len(items_a) == 1
    assert items_a[0].id == model_a.id

    # Owner B sees empty list
    items_b = await repo.list(owner_id=owner_b)
    assert len(items_b) == 0

    # Soft delete
    deleted = await repo.soft_delete(owner_id=owner_a, memory_id=model_a.id)
    assert deleted is True

    # After soft delete, regular get and list exclude the item
    assert await repo.get_by_id(owner_id=owner_a, memory_id=model_a.id) is None
    assert len(await repo.list(owner_id=owner_a)) == 0

    # include_deleted=True returns it
    model_retrieved = await repo.get_by_id(
        owner_id=owner_a, memory_id=model_a.id, include_deleted=True
    )
    assert model_retrieved is not None
    assert model_retrieved.deleted_at is not None


@pytest.mark.anyio
async def test_benchmark_fixture_loading_and_seeding():
    """Verify benchmark fixture parsing and seeding."""
    harness = MemoryRecallBenchmarkHarness()
    raw = harness.load_fixture()

    assert "metadata" in raw
    assert "seed_memories" in raw
    assert "questions" in raw
    assert len(raw["seed_memories"]) == 11
    assert len(raw["questions"]) == 20

    seed_count = await harness.setup_seed_memories()
    assert seed_count == 11

    # Check that repo storage has all 11 items
    assert len(harness.repository._storage) == 11


@pytest.mark.anyio
async def test_full_benchmark_execution():
    """Run the 20-question benchmark and verify retrieval metrics satisfy targets."""
    harness = MemoryRecallBenchmarkHarness()
    summary: BenchmarkSummary = await harness.run_benchmark()

    # Verify high-level counts
    assert summary.total_questions == 20
    assert summary.benchmark_name == "CortexStone 20-Question Memory Recall Evaluation"

    # Verify target accuracy threshold (>= 85%)
    assert summary.target_accuracy_threshold == 0.85
    assert summary.recall_rate >= 0.85, (
        f"Benchmark recall rate {summary.recall_rate} fell below required 0.85 threshold. "
        f"Passed: {summary.passed_questions}/20."
    )
    assert summary.threshold_met is True

    # Verify negative test accuracy (100% pass on negative controls)
    assert summary.negative_test_accuracy == 1.0, (
        f"Negative test accuracy {summary.negative_test_accuracy} must be 1.0 (no leaked data)."
    )

    # Verify citation precision and inference accuracy
    assert summary.citation_precision >= 0.85
    assert summary.inference_accuracy >= 0.85

    # Check category breakdown presence
    expected_categories = {
        "explicit_fact",
        "inferred_preference",
        "episodic_timeline",
        "approved_skill",
        "unapproved_skill",
        "deleted_memory_exclusion",
        "cross_owner_isolation",
        "unanswerable_no_memory",
    }
    assert set(summary.category_breakdown.keys()) == expected_categories

    for cat_data in summary.category_breakdown.values():
        assert cat_data["total"] > 0
        assert 0.0 <= cat_data["accuracy"] <= 1.0


@pytest.mark.anyio
async def test_benchmark_negative_controls_explicitly():
    """Explicitly test Q09 (deleted), Q10 (cross-owner), Q12 & Q13 (unanswerable)."""
    harness = MemoryRecallBenchmarkHarness()
    await harness.setup_seed_memories()

    fixture = harness.load_fixture()
    questions_by_id = {q["id"]: q for q in fixture["questions"]}

    # Q09: deleted memory exclusion
    q09 = questions_by_id["Q09"]
    res_09 = await harness.evaluate_question(q09, target_owner_id="eval_user_001")
    assert res_09.recall_pass is True
    assert "11111111-1111-1111-1111-111111111109" not in res_09.retrieved_memory_ids

    # Q10: cross owner isolation
    q10 = questions_by_id["Q10"]
    res_10 = await harness.evaluate_question(q10, target_owner_id="eval_user_001")
    assert res_10.recall_pass is True
    assert "22222222-2222-2222-2222-222222222201" not in res_10.retrieved_memory_ids

    # Q12: unanswerable query
    q12 = questions_by_id["Q12"]
    res_12 = await harness.evaluate_question(q12, target_owner_id="eval_user_001")
    assert res_12.recall_pass is True

    # Q13: unanswerable query
    q13 = questions_by_id["Q13"]
    res_13 = await harness.evaluate_question(q13, target_owner_id="eval_user_001")
    assert res_13.recall_pass is True
