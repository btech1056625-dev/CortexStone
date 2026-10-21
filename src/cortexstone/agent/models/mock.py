"""
src/cortexstone/agent/models/mock.py

MockModelClient for offline testing, CI/CD, and fast verification
without burning Nebius Token Factory credits.
"""
from __future__ import annotations

from typing import Any, TypeVar
from pydantic import BaseModel

from cortexstone.agent.models.interface import (
    ModelClient,
    ModelRole,
    ModelMessage,
    ModelResponse,
    UsageMetadata,
)

T = TypeVar("T", bound=BaseModel)


class MockModelClient(ModelClient):
    """
    Deterministic mock client recording calls and returning preset responses.
    """

    def __init__(
        self,
        fixed_text: str = "Mock model response",
        parsed_fixture: Any = None,
        simulate_error: Exception | None = None,
    ) -> None:
        self.fixed_text = fixed_text
        self.parsed_fixture = parsed_fixture
        self.simulate_error = simulate_error
        self.recorded_calls: list[dict[str, Any]] = []

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
        return await self.generate(
            messages=messages,
            schema=schema,
            model_id=f"mock-{role.value}",
            temperature=temperature,
            max_tokens=max_tokens or 512,
            timeout=timeout or 10.0,
        )

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
        if self.simulate_error is not None:
            raise self.simulate_error

        self.recorded_calls.append({
            "model_id": model_id or "mock-model",
            "messages": messages,
            "schema": schema,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })

        parsed: T | None = None
        if schema is not None and self.parsed_fixture is not None:
            if isinstance(self.parsed_fixture, schema):
                parsed = self.parsed_fixture
            elif isinstance(self.parsed_fixture, dict):
                parsed = schema.model_validate(self.parsed_fixture)

        return ModelResponse(
            raw_content=self.fixed_text,
            parsed=parsed,
            model_id=model_id or "mock-model",
            finish_reason="stop",
            usage=UsageMetadata(
                prompt_tokens=15,
                completion_tokens=25,
                total_tokens=40,
                latency_ms=2.5,
            ),
        )
