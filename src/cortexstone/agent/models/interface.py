"""
src/cortexstone/agent/models/interface.py

Defines the provider-neutral ModelClient contract, domain types,
and model-layer exceptions for Cortexstone.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelRole(str, enum.Enum):
    """Identifies the operational tier for model routing."""

    ROUTER = "router"  # Nemotron Mini: Intent classification & complexity routing
    REASONER = "reasoner"  # Nemotron 3 Super 120B A12B: Complex reasoning and planning


class Role(str, enum.Enum):
    """Chat message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ModelMessage:
    """A single bounded message within a model inference request."""

    role: Role
    content: str
    name: str | None = None

    def to_dict(self) -> dict[str, str]:
        data: dict[str, str] = {"role": self.role.value, "content": self.content}
        if self.name:
            data["name"] = self.name
        return data


@dataclass
class UsageMetadata:
    """Token consumption and latency tracking for inference calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0


@dataclass
class ModelResponse(Generic[T]):
    """Parsed model response with execution metadata."""

    raw_content: str
    parsed: T | None = None
    model_id: str = ""
    finish_reason: str = "stop"
    usage: UsageMetadata = field(default_factory=UsageMetadata)


# --- Exceptions ---


class ModelError(Exception):
    """Base exception for all model operations."""


class ModelTimeoutError(ModelError):
    """Raised when inference exceeds configured timeout."""


class ModelRateLimitError(ModelError):
    """Raised on 429 Too Many Requests / Token Factory quota exceeded."""


class ModelAuthenticationError(ModelError):
    """Raised when API key / Token Factory authentication fails."""


class ModelSchemaValidationError(ModelError):
    """Raised when model response fails schema parsing and cannot be validated."""


@runtime_checkable
class ModelClient(Protocol):
    """
    Provider-neutral interface for language model inference.
    Implementations must:
      1. Never log raw API credentials or unredacted sensitive prompts.
      2. Enforce timeouts and bounded token limits.
      3. Validate structured output if a schema is provided.
      4. Remain replaceable without impacting backend business policy.
    """

    async def generate(
        self,
        messages: list[ModelMessage],
        schema: type[T] | None = None,
        *,
        model_id: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 30.0,
    ) -> ModelResponse[T]:
        """Send messages to the model and return a validated response."""
        ...

    async def generate_for_role(
        self,
        role: ModelRole,
        messages: list[ModelMessage],
        schema: type[T] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> ModelResponse[T]:
        """Dispatch inference to the model mapped to a specific ModelRole."""
        ...
