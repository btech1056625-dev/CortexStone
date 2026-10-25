"""Validated application-level chat input and result contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cortexstone.agent.schemas.actions import ProposedAction

ChatAnswer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=20_000),
]


class ChatTurn(BaseModel):
    """A bounded user chat message and optional correlation identifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=10_000),
    ]
    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ChatResult(BaseModel):
    """Validated assistant answer or typed, unexecuted action proposals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    answer: ChatAnswer | None = None
    proposed_actions: list[ProposedAction] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_answer_or_action(self) -> "ChatResult":
        if self.answer is None and not self.proposed_actions:
            raise ValueError("A chat result must include an answer or proposed action")
        return self
