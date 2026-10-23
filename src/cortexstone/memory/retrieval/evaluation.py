"""Offline evaluation harness for the CortexStone 20-question memory-recall benchmark.

Provides an offline, deterministic evaluation framework to evaluate:
1. Retrieval Recall (Target: >= 85%): Verifies relevant memory items are retrieved in top-k.
2. Citation Precision: Verifies retrieved memory items format valid citations
   [Source: <type>:<ref>].
3. Inference Accuracy: Verifies inferred memories carry explicit [INFERRED] indicators.
4. Tenant Isolation & Soft-Deletion Exclusion: Verifies negative controls (deleted records,
   foreign owners, and unanswerable queries) do not leak unauthorized or deleted data.

Requires zero external API calls, zero API keys, and zero live database connections.
"""

from __future__ import annotations

import builtins
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from cortexstone.db.base import utc_now
from cortexstone.db.models.memory import MemoryItemModel
from cortexstone.memory.embeddings.base import EmbeddingProvider
from cortexstone.memory.repositories.base import MemoryRepositoryInterface
from cortexstone.memory.retrieval.formatter import (
    format_memory_context,
    format_memory_item_citation,
)
from cortexstone.memory.retrieval.ranking import RankingConfig
from cortexstone.memory.retrieval.retriever import (
    MemoryRetrievalService,
    RetrievalRequest,
    RetrievalResult,
)
from cortexstone.memory.schemas import (
    MemoryFilter,
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryKind,
    SensitivityLevel,
)

STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
}


def _stem_word(word: str) -> str:
    """Deterministic suffix stemming for common English inflectional endings."""
    w = word.lower()
    for sfx in ("ing", "tion", "tions", "ies", "es", "ed", "s"):
        if w.endswith(sfx) and len(w) - len(sfx) >= 3:
            return w[: -len(sfx)]
    return w


class DeterministicLexicalEmbeddingProvider(EmbeddingProvider):
    """Deterministic, offline embedding provider using n-gram hashing and term weighting.

    Generates reproducible, L2-normalized float vectors from text.
    Tokens and character 3-grams are mapped into a fixed vector dimension.
    Overlapping lexical terms yield positive cosine similarities, while unrelated
    texts yield near-zero similarities.
    """

    def __init__(self, dimension: int = 128) -> None:
        if dimension <= 0:
            raise ValueError("Dimension must be positive.")
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "deterministic-lexical-offline"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _text_to_vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        clean = text.lower().strip()
        if not clean:
            vec[0] = 1.0
            return vec

        raw_words = re.findall(r"[a-z0-9_]+", clean)
        for raw in raw_words:
            w = _stem_word(raw)
            weight = 0.2 if raw in STOP_WORDS else 3.0
            h = 0
            for ch in w:
                h = (h * 31 + ord(ch)) & 0xFFFFFFFF
            idx = h % self._dimension
            vec[idx] += weight

            # Subword 3-grams within significant content words
            if raw not in STOP_WORDS and len(w) >= 4:
                for i in range(len(w) - 2):
                    tri = w[i : i + 3]
                    th = 0
                    for ch in tri:
                        th = (th * 37 + ord(ch)) & 0xFFFFFFFF
                    t_idx = th % self._dimension
                    vec[t_idx] += 0.5

        # L2 Normalize
        sq_sum = sum(x * x for x in vec)
        if sq_sum > 0.0:
            norm = math.sqrt(sq_sum)
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0

        return vec

    async def embed_text(self, text: str) -> list[float]:
        return self._text_to_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._text_to_vector(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._text_to_vector(query)

    async def embed_document(self, document: str) -> list[float]:
        return self._text_to_vector(document)


class InMemoryMemoryRepository(MemoryRepositoryInterface):
    """In-memory implementation of MemoryRepositoryInterface for fast, offline testing.

    Enforces mandatory owner scoping, soft-deletion exclusion, and deterministic ordering.
    """

    def __init__(self) -> None:
        self._storage: dict[UUID, MemoryItemModel] = {}

    def seed_model(self, model: MemoryItemModel) -> None:
        """Seed a MemoryItemModel directly into the repository storage."""
        self._storage[model.id] = model

    async def create(
        self,
        owner_id: str,
        item: MemoryItemCreate,
    ) -> MemoryItemModel:
        if not owner_id or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string.")

        now = utc_now()
        metadata_dict = dict(item.metadata)
        if item.is_inferred:
            metadata_dict["is_inferred"] = True

        model = MemoryItemModel(
            owner_id=owner_id.strip(),
            kind=item.kind.value if isinstance(item.kind, MemoryKind) else str(item.kind),
            title=item.title,
            content=item.content,
            sensitivity=(
                item.sensitivity.value
                if isinstance(item.sensitivity, SensitivityLevel)
                else str(item.sensitivity)
            ),
            approved=False,
            source_type=item.source_type,
            source_ref=item.source_ref,
            confidence=item.confidence,
            occurred_at=item.occurred_at,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            metadata_=metadata_dict,
        )
        self._storage[model.id] = model
        return model

    async def get_by_id(
        self,
        owner_id: str,
        memory_id: UUID,
        include_deleted: bool = False,
    ) -> MemoryItemModel | None:
        clean_owner = owner_id.strip() if owner_id else ""
        model = self._storage.get(memory_id)
        if model is None:
            return None
        if model.owner_id != clean_owner:
            return None
        if model.deleted_at is not None and not include_deleted:
            return None
        return model

    async def list(
        self,
        owner_id: str,
        filter_params: MemoryFilter | None = None,
    ) -> builtins.list[MemoryItemModel]:
        clean_owner = owner_id.strip() if owner_id else ""
        if not clean_owner:
            return []

        results: list[MemoryItemModel] = []
        include_deleted = filter_params.include_deleted if filter_params else False

        for model in self._storage.values():
            if model.owner_id != clean_owner:
                continue
            if model.deleted_at is not None and not include_deleted:
                continue
            if filter_params:
                if filter_params.kind and model.kind != filter_params.kind:
                    continue
                if filter_params.sensitivity and model.sensitivity != filter_params.sensitivity:
                    continue
                if filter_params.approved_only and not model.approved:
                    continue
                if filter_params.occurred_after:
                    item_time = model.occurred_at or model.created_at
                    if item_time and item_time < filter_params.occurred_after:
                        continue
                if filter_params.occurred_before:
                    item_time = model.occurred_at or model.created_at
                    if item_time and item_time > filter_params.occurred_before:
                        continue
            results.append(model)

        # Deterministic sorting: -occurred_at/-created_at, then -created_at, then id
        def sort_key(m: MemoryItemModel):
            t1 = (m.occurred_at or m.created_at or datetime.min.replace(tzinfo=UTC)).timestamp()
            t2 = (m.created_at or datetime.min.replace(tzinfo=UTC)).timestamp()
            return (-t1, -t2, str(m.id))

        results.sort(key=sort_key)

        offset = filter_params.offset if filter_params else 0
        limit = filter_params.limit if filter_params else 100
        return results[offset : offset + limit]

    async def update(
        self,
        owner_id: str,
        memory_id: UUID,
        update_data: MemoryItemUpdate,
        allow_approval_change: bool = False,
    ) -> MemoryItemModel | None:
        model = await self.get_by_id(owner_id, memory_id, include_deleted=False)
        if model is None:
            return None

        update_dict = update_data.model_dump(exclude_unset=True)
        if "approved" in update_dict and not allow_approval_change:
            raise PermissionError(
                "Approval status can only be modified with explicit authorization."
            )

        for key, val in update_dict.items():
            if hasattr(model, key):
                setattr(model, key, val)

        model.updated_at = utc_now()
        return model

    async def soft_delete(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> bool:
        model = await self.get_by_id(owner_id, memory_id, include_deleted=False)
        if model is None:
            return False
        model.deleted_at = utc_now()
        model.updated_at = utc_now()
        return True

    async def hard_delete(
        self,
        owner_id: str,
        memory_id: UUID,
    ) -> bool:
        clean_owner = owner_id.strip() if owner_id else ""
        model = self._storage.get(memory_id)
        if model is None or model.owner_id != clean_owner:
            return False
        del self._storage[memory_id]
        return True


class QuestionEvaluationResult(BaseModel):
    """Result of evaluating a single benchmark question."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    query: str
    category: str
    expect_no_match: bool
    expected_memory_ids: list[str]
    retrieved_memory_ids: list[str]
    recall_pass: bool
    citation_pass: bool
    inference_tag_pass: bool
    overall_pass: bool
    details: str
    formatted_context: str


class BenchmarkSummary(BaseModel):
    """Aggregated evaluation metrics for the memory-recall benchmark."""

    model_config = ConfigDict(frozen=True)

    benchmark_name: str
    total_questions: int
    passed_questions: int
    failed_questions: int
    recall_rate: float
    citation_precision: float
    inference_accuracy: float
    negative_test_accuracy: float
    target_accuracy_threshold: float
    threshold_met: bool
    category_breakdown: dict[str, dict[str, Any]]
    results: list[QuestionEvaluationResult]


class MemoryRecallBenchmarkHarness:
    """Benchmark runner for offline memory-recall evaluation."""

    def __init__(
        self,
        fixture_path: str | Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        ranking_config: RankingConfig | None = None,
    ) -> None:
        if fixture_path is None:
            # Default to canonical test fixture
            repo_root = Path(__file__).resolve().parents[4]
            self.fixture_path = repo_root / "tests" / "fixtures" / "memory_eval_20_questions.json"
        else:
            self.fixture_path = Path(fixture_path)

        self.embedding_provider = embedding_provider or DeterministicLexicalEmbeddingProvider(
            dimension=128
        )
        self.ranking_config = ranking_config or RankingConfig(
            semantic_weight=0.85,
            recency_weight=0.08,
            confidence_weight=0.07,
            half_life_days=90.0,
        )

        self._raw_fixture: dict[str, Any] = {}
        self.repository = InMemoryMemoryRepository()
        self.retrieval_service = MemoryRetrievalService(
            repository=self.repository,
            embedding_provider=self.embedding_provider,
            ranking_config=self.ranking_config,
        )

    def load_fixture(self) -> dict[str, Any]:
        """Load and parse the JSON benchmark fixture."""
        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Benchmark fixture not found at {self.fixture_path}")
        with open(self.fixture_path, encoding="utf-8") as f:
            self._raw_fixture = json.load(f)
        return self._raw_fixture

    async def setup_seed_memories(self) -> int:
        """Seed memories from fixture into the repository with computed embeddings."""
        if not self._raw_fixture:
            self.load_fixture()

        seeds = self._raw_fixture.get("seed_memories", [])
        for seed in seeds:
            mem_id = UUID(seed["id"])
            owner_id = seed["owner_id"]
            kind = MemoryKind(seed["kind"])
            title = seed.get("title")
            content = seed["content"]
            source_type = seed.get("source_type")
            source_ref = seed.get("source_ref")
            confidence = float(seed.get("confidence", 1.0))
            is_inferred = bool(seed.get("is_inferred", False))
            approved = bool(seed.get("approved", True))
            sensitivity = SensitivityLevel(seed.get("sensitivity", "normal"))

            occurred_at = None
            if seed.get("occurred_at"):
                occurred_at = datetime.fromisoformat(seed["occurred_at"].replace("Z", "+00:00"))

            deleted_at = None
            if seed.get("deleted_at"):
                deleted_at = datetime.fromisoformat(seed["deleted_at"].replace("Z", "+00:00"))

            # Compute offline embedding vector across title, content, and provenance sources
            full_text = f"{title or ''} {content} {source_type or ''} {source_ref or ''}".strip()
            embedding_vec = await self.embedding_provider.embed_document(full_text)

            model = MemoryItemModel(
                id=mem_id,
                owner_id=owner_id,
                kind=kind.value if isinstance(kind, MemoryKind) else str(kind),
                title=title,
                content=content,
                sensitivity=(
                    sensitivity.value
                    if isinstance(sensitivity, SensitivityLevel)
                    else str(sensitivity)
                ),
                approved=approved,
                source_type=source_type,
                source_ref=source_ref,
                confidence=confidence,
                occurred_at=occurred_at,
                created_at=occurred_at or utc_now(),
                updated_at=occurred_at or utc_now(),
                deleted_at=deleted_at,
                embedding=embedding_vec,
                metadata_={"is_inferred": is_inferred},
            )
            self.repository.seed_model(model)

        return len(seeds)

    async def evaluate_question(
        self,
        question_data: dict[str, Any],
        target_owner_id: str,
    ) -> QuestionEvaluationResult:
        """Evaluate a single question against the retrieval service."""
        q_id = question_data["id"]
        query = question_data["query"]
        category = question_data.get("category", "general")
        expect_no_match = question_data.get("expect_no_match", False)
        expected_ids = question_data.get("expected_memory_ids", [])
        expected_source = question_data.get("expected_source")
        is_inferred_expected = question_data.get("is_inferred", False)

        # Execute retrieval with target owner
        req = RetrievalRequest(query=query, top_k=5)
        res: RetrievalResult = await self.retrieval_service.retrieve(
            owner_id=target_owner_id,
            request=req,
        )

        retrieved_ids = [str(item.item.id) for item in res.items]
        formatted_context = format_memory_context(res.items)

        # 1. Recall check
        recall_pass = False
        if expect_no_match:
            # Negative test evaluation:
            # - For deleted memory exclusion: the deleted ID must NOT appear
            # - For cross owner isolation: the other owner's ID must NOT appear
            # - For unanswerable queries: prohibited/leaked IDs must not appear
            prohibited_ids = {
                "11111111-1111-1111-1111-111111111109",
                "22222222-2222-2222-2222-222222222201",
            }
            if category == "deleted_memory_exclusion":
                # Ensure memory 1109 is not in retrieved results
                recall_pass = "11111111-1111-1111-1111-111111111109" not in retrieved_ids
            elif category == "cross_owner_isolation":
                # Ensure memory 2201 is not in retrieved results
                recall_pass = "22222222-2222-2222-2222-222222222201" not in retrieved_ids
            elif category == "unanswerable_no_memory":
                # For unanswerable questions, verify no unauthorized or deleted items leak
                recall_pass = all(pid not in retrieved_ids for pid in prohibited_ids)
            else:
                recall_pass = all(pid not in retrieved_ids for pid in prohibited_ids)
        else:
            # Positive test: all expected IDs must be present in retrieved_ids
            recall_pass = all(exp_id in retrieved_ids for exp_id in expected_ids)

        # 2. Citation check
        citation_pass = True
        if not expect_no_match and res.items:
            # Find the top result corresponding to expected_ids
            top_match = next(
                (item for item in res.items if str(item.item.id) in expected_ids), None
            )
            if top_match:
                item_citation = format_memory_item_citation(top_match.item)
                # Check valid citation syntax
                if not item_citation.startswith("[Source: ") or "]" not in item_citation:
                    citation_pass = False
                # If expected source specified, check it
                if expected_source and expected_source not in item_citation:
                    citation_pass = False
            else:
                citation_pass = False

        # 3. Inference tag check
        inference_tag_pass = True
        if not expect_no_match and res.items:
            top_match = next(
                (item for item in res.items if str(item.item.id) in expected_ids), None
            )
            if top_match:
                item_citation = format_memory_item_citation(top_match.item)
                has_inferred_tag = "[INFERRED]" in item_citation
                if is_inferred_expected != has_inferred_tag:
                    inference_tag_pass = False

        overall_pass = recall_pass and citation_pass and inference_tag_pass
        details = (
            f"Recall: {recall_pass}, Citation: {citation_pass}, "
            f"InferenceTag: {inference_tag_pass}. "
            f"Retrieved: {retrieved_ids[:2]}"
        )

        return QuestionEvaluationResult(
            question_id=q_id,
            query=query,
            category=category,
            expect_no_match=expect_no_match,
            expected_memory_ids=expected_ids,
            retrieved_memory_ids=retrieved_ids,
            recall_pass=recall_pass,
            citation_pass=citation_pass,
            inference_tag_pass=inference_tag_pass,
            overall_pass=overall_pass,
            details=details,
            formatted_context=formatted_context,
        )

    async def run_benchmark(self) -> BenchmarkSummary:
        """Run the full benchmark suite across all questions in the fixture."""
        if not self._raw_fixture:
            self.load_fixture()
        await self.setup_seed_memories()

        meta = self._raw_fixture.get("metadata", {})
        benchmark_name = meta.get("benchmark_name", "CortexStone Memory Recall Evaluation")
        target_owner_id = meta.get("target_owner_id", "eval_user_001")
        target_threshold = float(meta.get("target_accuracy_threshold", 0.85))

        questions = self._raw_fixture.get("questions", [])
        results: list[QuestionEvaluationResult] = []

        # Category trackers
        cat_counts: dict[str, dict[str, int]] = {}

        for q in questions:
            cat = q.get("category", "other")
            if cat not in cat_counts:
                cat_counts[cat] = {"total": 0, "passed": 0}
            cat_counts[cat]["total"] += 1

            eval_res = await self.evaluate_question(q, target_owner_id=target_owner_id)
            results.append(eval_res)

            if eval_res.overall_pass:
                cat_counts[cat]["passed"] += 1

        total_questions = len(results)
        passed_questions = sum(1 for r in results if r.overall_pass)
        failed_questions = total_questions - passed_questions

        # Metric calculations
        recall_pass_count = sum(1 for r in results if r.recall_pass)
        recall_rate = round(recall_pass_count / total_questions, 4) if total_questions else 0.0

        positive_questions = [r for r in results if not r.expect_no_match]
        citation_pass_count = sum(1 for r in positive_questions if r.citation_pass)
        citation_precision = (
            round(citation_pass_count / len(positive_questions), 4) if positive_questions else 1.0
        )

        inference_pass_count = sum(1 for r in positive_questions if r.inference_tag_pass)
        inference_accuracy = (
            round(inference_pass_count / len(positive_questions), 4) if positive_questions else 1.0
        )

        negative_questions = [r for r in results if r.expect_no_match]
        neg_pass_count = sum(1 for r in negative_questions if r.overall_pass)
        negative_test_accuracy = (
            round(neg_pass_count / len(negative_questions), 4) if negative_questions else 1.0
        )

        # Build category breakdown
        category_breakdown: dict[str, dict[str, Any]] = {}
        for cat, data in cat_counts.items():
            tot = data["total"]
            pas = data["passed"]
            acc = round(pas / tot, 4) if tot > 0 else 0.0
            category_breakdown[cat] = {
                "total": tot,
                "passed": pas,
                "accuracy": acc,
            }

        threshold_met = recall_rate >= target_threshold

        return BenchmarkSummary(
            benchmark_name=benchmark_name,
            total_questions=total_questions,
            passed_questions=passed_questions,
            failed_questions=failed_questions,
            recall_rate=recall_rate,
            citation_precision=citation_precision,
            inference_accuracy=inference_accuracy,
            negative_test_accuracy=negative_test_accuracy,
            target_accuracy_threshold=target_threshold,
            threshold_met=threshold_met,
            category_breakdown=category_breakdown,
            results=results,
        )
