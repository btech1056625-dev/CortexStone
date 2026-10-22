"""Unit tests verifying the integrity, coverage, and evaluation schema of the 20-question benchmark."""

import json
import os
import pytest
from uuid import UUID

from cortexstone.memory.schemas import MemoryKind, SensitivityLevel


FIXTURE_PATH = os.path.join("tests", "fixtures", "memory_eval_20_questions.json")


def load_benchmark_fixture():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_benchmark_fixture_exists_and_loads():
    """Verify fixture file exists and is valid JSON."""
    assert os.path.isfile(FIXTURE_PATH)
    data = load_benchmark_fixture()
    assert "metadata" in data
    assert "seed_memories" in data
    assert "questions" in data


def test_benchmark_metadata_integrity():
    """Verify metadata targets and threshold."""
    data = load_benchmark_fixture()
    meta = data["metadata"]
    assert meta["target_accuracy_threshold"] == 0.85
    assert meta["target_owner_id"] == "eval_user_001"
    assert meta["other_owner_id"] == "eval_user_002"


def test_seed_memories_schema_conformance():
    """Verify all seed memories conform to valid domain schema fields."""
    data = load_benchmark_fixture()
    seeds = data["seed_memories"]
    assert len(seeds) >= 10

    valid_kinds = {k.value for k in MemoryKind}
    valid_sensitivities = {s.value for s in SensitivityLevel}

    for mem in seeds:
        # Validate UUID format
        UUID(mem["id"])
        assert mem["owner_id"] in ("eval_user_001", "eval_user_002")
        assert mem["kind"] in valid_kinds
        assert mem["sensitivity"] in valid_sensitivities
        assert isinstance(mem["content"], str) and len(mem["content"]) > 0
        assert isinstance(mem["confidence"], (int, float)) and 0.0 <= mem["confidence"] <= 1.0
        assert isinstance(mem["is_inferred"], bool)


def test_twenty_questions_count_and_categories():
    """Verify exactly 20 questions with complete category coverage."""
    data = load_benchmark_fixture()
    questions = data["questions"]
    assert len(questions) == 20

    question_ids = [q["id"] for q in questions]
    assert len(set(question_ids)) == 20  # All unique IDs

    categories = {q["category"] for q in questions}
    # Verify core coverage categories
    assert "explicit_fact" in categories
    assert "inferred_preference" in categories
    assert "episodic_timeline" in categories
    assert "approved_skill" in categories
    assert "unapproved_skill" in categories
    assert "deleted_memory_exclusion" in categories
    assert "cross_owner_isolation" in categories
    assert "unanswerable_no_memory" in categories


def test_adversarial_and_negative_test_cases():
    """Verify negative test questions (deleted, foreign user, unanswerable) expect no matches."""
    data = load_benchmark_fixture()
    questions = data["questions"]

    negative_questions = [q for q in questions if q["expect_no_match"]]
    assert len(negative_questions) >= 4

    for q in negative_questions:
        assert q["expected_memory_ids"] == []
        assert q["expected_source"] is None


def test_citation_formatting_compliance():
    """Verify expected sources adhere to the format `source_type:source_ref`."""
    data = load_benchmark_fixture()
    questions = data["questions"]

    for q in questions:
        if not q["expect_no_match"]:
            src = q["expected_source"]
            assert ":" in src
            parts = src.split(":")
            assert len(parts) == 2
            assert len(parts[0]) > 0
            assert len(parts[1]) > 0
