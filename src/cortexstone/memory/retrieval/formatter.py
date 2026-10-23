"""Memory context formatting utilities for LLM prompts.

Formats retrieved memory items into structured <memory_context> XML blocks
with explicit provenance citations, timestamps, confidence indicators, and
clear distinction between confirmed facts and uncertain inferences.

Invariants:
1. Retrieved records are treated as untrusted data; content and titles are escaped and bounded.
2. Embedded XML markup in untrusted text cannot escape or terminate the <memory_context> boundary.
3. Every item cites its source reference, observation timestamp, and confidence.
4. Inferred records are explicitly tagged as INFERRED to prevent hallucination.
5. If no records are retrieved, returns a standardized empty context block.
"""

from cortexstone.memory.schemas import MemoryItemRead, MemorySearchResult

DEFAULT_MAX_TITLE_CHARS: int = 255
DEFAULT_MAX_CONTENT_CHARS: int = 4000
DEFAULT_MAX_CONTEXT_CHARS: int = 30_000
OPENING_TAG: str = "<memory_context>"
CLOSING_TAG: str = "</memory_context>"
MIN_CONTEXT_CHARS: int = len(f"{OPENING_TAG}\n{CLOSING_TAG}")  # 34
TRUNCATION_NOTICE: str = "   ... [additional memories truncated due to context length limit]"


def _render_context(body_lines: list[str]) -> str:
    """Render the XML context block from body lines, stripping trailing empty lines."""
    lines = list(body_lines)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join([OPENING_TAG, *lines, CLOSING_TAG])


def _escape_untrusted_text(text: str) -> str:
    """Escape XML structural characters in untrusted memory text to prevent prompt injection.

    Converts '&', '<', and '>' to their standard XML entities '&amp;', '&lt;', and '&gt;'.
    Quotes are preserved to maintain standard prose readability in prompt context.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sanitize_and_bound_title(title: str | None, max_chars: int = DEFAULT_MAX_TITLE_CHARS) -> str:
    """Sanitize, bound, and escape an untrusted memory title."""
    if not title:
        return ""
    clean = title.strip()
    if len(clean) > max_chars:
        clean = clean[: max_chars - 3] + "..."
    return _escape_untrusted_text(clean)


def _sanitize_and_bound_content(
    content: str, max_chars: int = DEFAULT_MAX_CONTENT_CHARS
) -> list[str]:
    """Sanitize, bound, and split untrusted memory content into safe lines.

    Ensures content length is bounded, XML characters are escaped, and lines
    are stripped of trailing whitespace while preserving internal structure.
    """
    clean = content.strip()
    if len(clean) > max_chars:
        clean = clean[:max_chars] + "\n... [content truncated]"
    escaped = _escape_untrusted_text(clean)
    return escaped.splitlines()


def format_memory_item_citation(item: MemoryItemRead) -> str:
    """Construct a standardized citation string for a memory item.

    Example output:
        `[Source: github:issue#101, 2026-10-12 14:30:00Z | Conf: 0.90]`
    """
    prov = item.provenance
    src_type = _escape_untrusted_text(prov.source_type or "system")
    src_ref = _escape_untrusted_text(prov.source_ref or item.id.hex[:8])

    # Timestamp preference: occurred_at (real-world event time) > created_at
    ts = item.occurred_at or item.created_at
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%SZ") if ts else "unknown-time"

    conf_str = f"{prov.confidence:.2f}" if prov.confidence is not None else "unspecified"
    infer_tag = " [INFERRED]" if prov.is_inferred else ""

    return f"[Source: {src_type}:{src_ref}, {ts_str} | Conf: {conf_str}{infer_tag}]"


def format_memory_context(
    results: list[MemorySearchResult],
    max_items: int | None = None,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """Format a list of retrieved MemorySearchResult items into a prompt-ready context block.

    Untrusted memory text (titles, contents, and source refs) is safely escaped and bounded
    to prevent prompt injection, tag-escaping attacks (e.g. injected </memory_context>), and
    context buffer overflow.

    Guarantees:
    - Result length is strictly <= max_context_chars.
    - Opening and closing <memory_context> tags are always completely preserved.
    - Individual item titles and contents are bounded before line assembly.
    - First item and subsequent items are all bounded by max_context_chars.
    - Truncation notice is only appended if it fits within max_context_chars.

    Args:
        results: Ranked list of search results.
        max_items: Optional limit on the number of formatted items.
        max_content_chars: Maximum character length per memory content item before truncation.
        max_context_chars: Maximum overall character length for the rendered context block.
            Must be >= MIN_CONTEXT_CHARS (34) to preserve opening and closing tags.

    Returns:
        Structured XML-tagged string with <memory_context> ... </memory_context>.

    Raises:
        ValueError: If max_context_chars is less than MIN_CONTEXT_CHARS (34).
    """
    if max_context_chars < MIN_CONTEXT_CHARS:
        raise ValueError(
            f"max_context_chars must be at least {MIN_CONTEXT_CHARS} to preserve "
            f"{OPENING_TAG} ... {CLOSING_TAG} tags, got {max_context_chars}."
        )

    if not results:
        standard_empty = f"{OPENING_TAG}\nNo relevant memories found.\n{CLOSING_TAG}"
        if len(standard_empty) <= max_context_chars:
            return standard_empty
        return _render_context([])

    items_to_format = results[:max_items] if max_items is not None else results
    body_lines: list[str] = []
    items_fully_added = 0

    for idx, res in enumerate(items_to_format, start=1):
        item = res.item
        citation = format_memory_item_citation(item)
        score_info = f"[Score: {res.relevance_score:.2f}]"
        kind_tag = f"[{item.kind.value.upper()}]"

        safe_title = _sanitize_and_bound_title(item.title)
        title_part = f" - {safe_title}" if safe_title else ""
        header_line = f"{idx}. {kind_tag} {citation} {score_info}{title_part}"

        content_lines = _sanitize_and_bound_content(item.content, max_chars=max_content_chars)
        spacing = [""] if body_lines else []
        item_lines = spacing + [header_line] + [f"   {c}" for c in content_lines]

        candidate = body_lines + item_lines
        if len(_render_context(candidate)) <= max_context_chars:
            body_lines = candidate
            items_fully_added += 1
        else:
            if idx == 1:
                cand_header = body_lines + spacing + [header_line]
                if len(_render_context(cand_header)) <= max_context_chars:
                    body_lines = cand_header
                    for c_line in content_lines:
                        cand_line = body_lines + [f"   {c_line}"]
                        if len(_render_context(cand_line)) <= max_context_chars:
                            body_lines = cand_line
                        else:
                            break
            break

    if items_fully_added < len(items_to_format) and len(items_to_format) > 1:
        candidate_with_notice = body_lines + [TRUNCATION_NOTICE]
        if len(_render_context(candidate_with_notice)) <= max_context_chars:
            body_lines = candidate_with_notice

    return _render_context(body_lines)
