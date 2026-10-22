"""Memory domain schemas, enums, and validation models.

Defines Pydantic v2 domain representations for:
- Memory kinds: fact, episode, skill
- Sensitivity levels: normal, sensitive, internal
- Provenance and observation metadata
- Creation, update, read, and retrieval contracts

Note on Security & Identity:
Ownership (owner_id) must be established by server-side authentication
and injected into memory operations; clients and models are not trusted
to assert or spoof owner_id.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class MemoryKind(str, Enum):
    """Supported memory classifications."""

    FACT = "fact"
    EPISODE = "episode"
    SKILL = "skill"


class SensitivityLevel(str, Enum):
    """Sensitivity classification for memory items."""

    NORMAL = "normal"
    SENSITIVE = "sensitive"
    INTERNAL = "internal"


class MemoryProvenance(BaseModel):
    """Provenance tracking for memory origin, context, and certainty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: Optional[str] = Field(
        default=None,
        description="Type of source: conversation, tool_result, user_direct, system, external.",
    )
    source_ref: Optional[str] = Field(
        default=None,
        description="Identifier or reference of the source (e.g., message_id, job_id, doc_id).",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 (uncertain inference) and 1.0 (verified fact).",
    )
    is_inferred: bool = Field(
        default=False,
        description="Explicit flag distinguishing inferred preferences from explicitly stated facts.",
    )


class MemoryItemBase(BaseModel):
    """Base fields shared by memory creation and read schemas."""

    kind: MemoryKind = Field(..., description="Classification of the memory item.")
    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional title or brief summary for dashboard/inspector display.",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Body of the memory. Must never contain raw secrets or credentials.",
    )
    occurred_at: Optional[datetime] = Field(
        default=None,
        description="When the event occurred in the real world (UTC).",
    )
    sensitivity: SensitivityLevel = Field(
        default=SensitivityLevel.NORMAL,
        description="Sensitivity classification level.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
        description="Structured auxiliary attributes.",
    )

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Memory content must not be blank or whitespace-only.")
        return trimmed

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at_timezone(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("occurred_at must be a timezone-aware datetime (UTC).")
        return v


class MemoryItemCreate(MemoryItemBase):
    """Payload for creating a new memory record.

    Note: owner_id is NOT accepted from client request bodies. It must be
    supplied by the authenticated session in the service/repository layer.
    """

    source_type: Optional[str] = Field(default=None)
    source_ref: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_inferred: bool = Field(
        default=False,
        description="True if derived by model inference; False if explicitly user-stated.",
    )
    # Skills default to unapproved. Client cannot self-approve on creation.
    approved: bool = Field(
        default=False,
        description="Whether a skill is approved for execution. Default is False.",
    )


class MemoryItemUpdate(BaseModel):
    """Payload for modifying an existing memory record."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=255)
    content: Optional[str] = Field(default=None, min_length=1)
    occurred_at: Optional[datetime] = Field(default=None)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sensitivity: Optional[SensitivityLevel] = Field(default=None)
    approved: Optional[bool] = Field(
        default=None,
        description="Can only be toggled via explicit authorization/approval workflows.",
    )
    metadata: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            trimmed = v.strip()
            if not trimmed:
                raise ValueError("Updated content must not be blank or whitespace-only.")
            return trimmed
        return v

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at_timezone(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("occurred_at must be a timezone-aware datetime (UTC).")
        return v


class MemoryItemRead(MemoryItemBase):
    """Domain representation of a stored memory record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: str = Field(..., description="Authenticated owner identifier.")
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    confidence: Optional[float] = None
    approved: bool
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        """Return True if memory has not been soft-deleted or forgotten."""
        return self.deleted_at is None

    @property
    def provenance(self) -> MemoryProvenance:
        """Construct structured provenance object."""
        is_inferred = bool(self.metadata.get("is_inferred", False))
        return MemoryProvenance(
            source_type=self.source_type,
            source_ref=self.source_ref,
            confidence=self.confidence,
            is_inferred=is_inferred,
        )


class MemorySearchResult(BaseModel):
    """Result item returned from semantic or temporal retrieval queries."""

    model_config = ConfigDict(from_attributes=True)

    item: MemoryItemRead
    relevance_score: float = Field(
        ...,
        description="Computed composite score combining semantic similarity and recency.",
    )
    semantic_distance: Optional[float] = Field(
        default=None,
        description="Cosine or L2 distance from query vector if semantic search was used.",
    )


class MemoryFilter(BaseModel):
    """Filters applied to memory retrieval and listing queries."""

    model_config = ConfigDict(extra="forbid")

    kind: Optional[MemoryKind] = None
    source_type: Optional[str] = None
    sensitivity: Optional[SensitivityLevel] = None
    approved_only: Optional[bool] = None
    occurred_after: Optional[datetime] = None
    occurred_before: Optional[datetime] = None
    include_deleted: bool = Field(
        default=False,
        description="Default False. Active retrieval MUST never include deleted items.",
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("occurred_after", "occurred_before")
    @classmethod
    def validate_filter_timestamp_timezone(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("Filter timestamps must be timezone-aware (UTC).")
        return v
