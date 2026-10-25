"""Validated HTTP request and response schemas for the version 1 API."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.memory.schemas import MemoryItemCreate, MemoryItemRead, MemoryKind
from cortexstone.security.policy import PolicyDecision, PolicyReason, PolicyStatus, RiskLevel

ChatMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=10_000),
]
ChatAnswer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=20_000),
]


class ChatRequest(BaseModel):
    """A user message with an optional opaque correlation ID."""

    model_config = ConfigDict(extra="forbid")

    message: ChatMessage
    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Opaque conversation identifier supplied by the client.",
    )


class ChatResponse(BaseModel):
    """An assistant answer and any bounded, unexecuted action proposals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Opaque conversation identifier associated with this response.",
    )
    answer: ChatAnswer | None = None
    proposed_actions: list[ProposedAction] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_answer_or_actions(self) -> "ChatResponse":
        if self.answer is None and not self.proposed_actions:
            raise ValueError("A chat response must include an answer or proposed action")
        return self


class CurrentUserResponse(BaseModel):
    """Authenticated identity fields exposed to the frontend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    display_name: str
    authenticated: bool = True


class MemoryCreateRequest(BaseModel):
    """Frontend memory fields accepted for creating an owner-scoped memory."""

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, StringConstraints(strip_whitespace=True, strict=True, min_length=1)]
    memory_type: MemoryKind

    def to_domain(self) -> MemoryItemCreate:
        return MemoryItemCreate(
            content=self.content,
            kind=self.memory_type,
            source_type="user",
            confidence=1.0,
        )


class MemoryResponse(BaseModel):
    """Stable frontend memory representation without owner or embedding data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    memory_type: MemoryKind
    source: str | None
    confidence: float | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def from_memory(cls, memory: MemoryItemRead) -> "MemoryResponse":
        return cls(
            id=str(memory.id),
            content=memory.content,
            memory_type=memory.kind,
            source=memory.source_type,
            confidence=memory.confidence,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )


class MemoryPageResponse(BaseModel):
    """Owner-scoped memory page matching the frontend contract."""

    model_config = ConfigDict(frozen=True)

    items: list[MemoryResponse]
    total: int
    limit: int
    offset: int


class ActionValidationRequest(BaseModel):
    """An action proposal to validate; authorization evidence is not accepted here."""

    model_config = ConfigDict(extra="forbid")

    action: ProposedAction


class ActionValidationResponse(BaseModel):
    """Backend policy outcome without executing the proposed action."""

    model_config = ConfigDict(extra="forbid")

    status: PolicyStatus
    reason: PolicyReason
    action_hash: str | None = None
    risk: RiskLevel | None = None

    @classmethod
    def from_decision(cls, decision: PolicyDecision) -> "ActionValidationResponse":
        return cls(
            status=decision.status,
            reason=decision.reason,
            action_hash=decision.action_hash,
            risk=decision.risk,
        )
