"""Validated HTTP request and response schemas for the version 1 API."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cortexstone.agent.schemas.actions import ProposedAction
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
    """A user message, optionally continuing an existing conversation."""

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

    model_config = ConfigDict(extra="forbid")

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
