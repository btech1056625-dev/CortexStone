"""Unit tests for memory context formatting and prompt injection safety."""

from datetime import UTC, datetime
from uuid import uuid4

from cortexstone.memory.retrieval.formatter import (
    format_memory_context,
    format_memory_item_citation,
)
from cortexstone.memory.schemas import (
    MemoryItemRead,
    MemoryKind,
    MemorySearchResult,
    SensitivityLevel,
)


def make_search_result(
    content: str,
    kind: MemoryKind = MemoryKind.FACT,
    title: str = None,
    source_type: str = "github",
    source_ref: str = "issue#101",
    confidence: float = 0.95,
    is_inferred: bool = False,
    occurred_at: datetime = None,
    relevance_score: float = 0.88,
) -> MemorySearchResult:
    dt = occurred_at or datetime(2026, 10, 15, 10, 30, 0, tzinfo=UTC)
    item = MemoryItemRead(
        id=uuid4(),
        owner_id="user_test",
        kind=kind,
        title=title,
        content=content,
        source_type=source_type,
        source_ref=source_ref,
        confidence=confidence,
        occurred_at=dt,
        sensitivity=SensitivityLevel.NORMAL,
        approved=False,
        metadata={"is_inferred": is_inferred},
        created_at=dt,
        updated_at=dt,
    )
    return MemorySearchResult(
        item=item,
        relevance_score=relevance_score,
        semantic_distance=0.12,
    )


def test_format_memory_context_empty():
    """Verify empty search results return safe standardized fallback."""
    formatted = format_memory_context([])
    assert "<memory_context>" in formatted
    assert "No relevant memories found." in formatted
    assert "</memory_context>" in formatted


def test_format_memory_item_citation_explicit_fact():
    """Verify explicit fact citation format."""
    res = make_search_result(
        content="Deploy to production on Tuesdays",
        kind=MemoryKind.FACT,
        source_type="slack",
        source_ref="msg_99",
        confidence=1.0,
        is_inferred=False,
    )
    citation = format_memory_item_citation(res.item)
    assert "[Source: slack:msg_99, 2026-10-15 10:30:00Z | Conf: 1.00]" == citation


def test_format_memory_item_citation_inferred():
    """Verify inferred memory is explicitly tagged as [INFERRED]."""
    res = make_search_result(
        content="User likely prefers dark mode",
        kind=MemoryKind.FACT,
        confidence=0.72,
        is_inferred=True,
    )
    citation = format_memory_item_citation(res.item)
    assert "[INFERRED]" in citation
    assert "Conf: 0.72" in citation


def test_format_memory_context_structured_output():
    """Verify multiple memories are formatted into numbered blocks with XML boundary tags."""
    r1 = make_search_result(
        content="Python 3.14 is installed",
        title="Python Environment",
        kind=MemoryKind.FACT,
        relevance_score=0.92,
    )
    r2 = make_search_result(
        content="Reviewed PR #12 with Raghav\nApproved deployment checklist",
        kind=MemoryKind.EPISODE,
        source_type="calendar",
        source_ref="meeting_sync",
        relevance_score=0.75,
    )

    formatted = format_memory_context([r1, r2])

    assert formatted.startswith("<memory_context>")
    assert formatted.endswith("</memory_context>")
    expected_line1 = (
        "1. [FACT] [Source: github:issue#101, 2026-10-15 10:30:00Z | Conf: 0.95] "
        "[Score: 0.92] - Python Environment"
    )
    expected_line2 = (
        "2. [EPISODE] [Source: calendar:meeting_sync, 2026-10-15 10:30:00Z | Conf: 0.95] "
        "[Score: 0.75]"
    )
    assert expected_line1 in formatted
    assert "   Python 3.14 is installed" in formatted
    assert expected_line2 in formatted
    assert "   Reviewed PR #12 with Raghav" in formatted
    assert "   Approved deployment checklist" in formatted


def test_format_memory_context_max_items_limit():
    """Verify max_items limits the rendered items."""
    r1 = make_search_result(content="item 1")
    r2 = make_search_result(content="item 2")
    r3 = make_search_result(content="item 3")

    formatted = format_memory_context([r1, r2, r3], max_items=2)
    assert "item 1" in formatted
    assert "item 2" in formatted
    assert "item 3" not in formatted
