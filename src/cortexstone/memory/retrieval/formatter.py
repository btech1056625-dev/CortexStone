"""Memory context formatting utilities for LLM prompts.

Formats retrieved memory items into structured <memory_context> XML blocks
with explicit provenance citations, timestamps, confidence indicators, and
clear distinction between confirmed facts and uncertain inferences.

Invariants:
1. Retrieved records are treated as untrusted data; content is safely escaped/bounded.
2. Every item cites its source reference, observation timestamp, and confidence.
3. Inferred records are explicitly tagged as INFERENCE to prevent hallucination.
4. If no records are retrieved, returns a standardized empty context block.
"""

from cortexstone.memory.schemas import MemoryItemRead, MemorySearchResult


def format_memory_item_citation(item: MemoryItemRead) -> str:
    """Construct a standardized citation string for a memory item.

    Example output:
        `[Source: github#42, 2026-10-12T14:30:00Z | Confidence: 0.90]`
    """
    prov = item.provenance
    src_type = prov.source_type or "system"
    src_ref = prov.source_ref or item.id.hex[:8]

    # Timestamp preference: occurred_at (real-world event time) > created_at
    ts = item.occurred_at or item.created_at
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%SZ") if ts else "unknown-time"

    conf_str = f"{prov.confidence:.2f}" if prov.confidence is not None else "unspecified"
    infer_tag = " [INFERRED]" if prov.is_inferred else ""

    return f"[Source: {src_type}:{src_ref}, {ts_str} | Conf: {conf_str}{infer_tag}]"


def format_memory_context(
    results: list[MemorySearchResult],
    max_items: int | None = None,
) -> str:
    """Format a list of retrieved MemorySearchResult items into a prompt-ready context block.

    Args:
        results: Ranked list of search results.
        max_items: Optional limit on the number of formatted items.

    Returns:
        Structured XML-tagged string with <memory_context> ... </memory_context>.
    """
    if not results:
        return "<memory_context>\nNo relevant memories found.\n</memory_context>"

    items_to_format = results[:max_items] if max_items is not None else results

    lines = ["<memory_context>"]
    for idx, res in enumerate(items_to_format, start=1):
        item = res.item
        citation = format_memory_item_citation(item)
        score_info = f"[Score: {res.relevance_score:.2f}]"
        kind_tag = f"[{item.kind.value.upper()}]"

        # Header line with citation, score, kind, and title (if present)
        title_part = f" - {item.title}" if item.title else ""
        lines.append(f"{idx}. {kind_tag} {citation} {score_info}{title_part}")

        # Indented content body
        content_lines = item.content.strip().splitlines()
        for c_line in content_lines:
            lines.append(f"   {c_line}")
        lines.append("")  # Empty spacing line between entries

    # Remove trailing empty line if present before closing tag
    if lines[-1] == "":
        lines.pop()

    lines.append("</memory_context>")
    return "\n".join(lines)
