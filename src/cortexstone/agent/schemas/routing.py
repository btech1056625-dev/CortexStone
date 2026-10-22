"""
src/cortexstone/agent/schemas/routing.py

Schemas for intent classification and complexity routing powered by Nemotron Mini.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field


class IntentCategory(enum.StrEnum):
    """Primary intent categories for Cortexstone."""

    DIRECT_CHAT = "direct_chat"  # Conversational, greetings, simple knowledge
    MEMORY_RECALL = "memory_recall"  # Retrieve past facts, decisions, meetings, notes
    MEMORY_FORGET = "memory_forget"  # Request to forget/delete stored memory
    TOOL_ACTION = "tool_action"  # Request to perform actions (GitHub, Calendar, Notes)
    GUARDIAN_SCAN = "guardian_scan"  # Request to scan repositories or inspect findings
    CLARIFICATION = "clarification"  # Ambiguous or missing essential details


class ComplexityLevel(enum.StrEnum):
    """Complexity tiers determining execution path and model allocation."""

    LOW = "low"  # Simple retrieval or conversational response; no complex planning
    MEDIUM = "medium"  # Single-step action proposal or filtered memory synthesis
    HIGH = "high"  # Multi-step workflow, high-impact write, or scheduled background job


class RouteDecision(BaseModel):
    """Structured routing outcome emitted by Nemotron Mini."""

    model_config = ConfigDict(extra="forbid")

    intent: IntentCategory = Field(description="The primary classification of the user request")
    complexity: ComplexityLevel = Field(
        description="Complexity assessment for resource allocation and bounded planning"
    )
    needs_reasoner: bool = Field(
        description="True if Nemotron 3 Super 120B must be invoked for multi-step reasoning"
    )
    extracted_entities: list[str] = Field(
        default_factory=list,
        description=(
            "Named entities, repositories, dates, topics, or issue numbers extracted from the query"
        ),
    )
    rationale: str = Field(
        description="Short justification of the routing decision (max 1-2 sentences)"
    )
