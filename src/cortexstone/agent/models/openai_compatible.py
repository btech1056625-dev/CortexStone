"""OpenAI-compatible chat completions model adapter."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from cortexstone.agent.models.interface import (
    ModelAuthenticationError,
    ModelClient,
    ModelError,
    ModelMessage,
    ModelRateLimitError,
    ModelResponse,
    ModelRole,
    ModelSchemaValidationError,
    ModelTimeoutError,
    UsageMetadata,
)

logger = logging.getLogger("cortexstone.agent.models.openai_compatible")
T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleClient(ModelClient):
    """Adapter for providers exposing OpenAI chat-completions APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
        provider_name: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError(f"{provider_name} API key must not be empty")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.provider_name = provider_name
        self._external_client = client

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Cortexstone/2.0",
        }

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
            temperature=temperature,
            max_tokens=max_tokens or (512 if role == ModelRole.ROUTER else 2048),
            timeout=timeout or (10.0 if role == ModelRole.ROUTER else 45.0),
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
        chosen_model = model_id or self.model_id
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": [message.to_dict() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}

        start_time = time.monotonic()
        client = self._external_client or httpx.AsyncClient()
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(
                f"{self.provider_name} request timed out after {timeout:.1f}s"
            ) from exc
        except httpx.RequestError as exc:
            raise ModelError(
                f"Network error communicating with {self.provider_name}: {type(exc).__name__}"
            ) from exc
        finally:
            if not self._external_client:
                await client.aclose()

        latency_ms = (time.monotonic() - start_time) * 1000.0
        if response.status_code in (401, 403):
            raise ModelAuthenticationError(
                f"{self.provider_name} authentication failed: invalid API key"
            )
        if response.status_code == 429:
            raise ModelRateLimitError(
                f"{self.provider_name} rate limit or quota exceeded (HTTP 429)"
            )
        if response.status_code >= 400:
            raise ModelError(f"{self.provider_name} error (HTTP {response.status_code})")

        data = response.json()
        choice = data["choices"][0]
        raw_text = choice["message"].get("content", "")
        usage_data = data.get("usage", {})
        parsed_model: T | None = None
        if schema is not None:
            parsed_model = self._parse_and_validate(raw_text, schema)

        return ModelResponse(
            raw_content=raw_text,
            parsed=parsed_model,
            model_id=chosen_model,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=UsageMetadata(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                latency_ms=latency_ms,
            ),
        )

    @staticmethod
    def _parse_and_validate(raw_text: str, schema: type[T]) -> T:
        clean_text = raw_text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if len(lines) >= 2:
                start_idx = 1 if lines[0].strip().startswith("```") else 0
                end_idx = -1 if lines[-1].strip() == "```" else len(lines)
                clean_text = "\n".join(lines[start_idx:end_idx]).strip()
        try:
            parsed_json = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            raise ModelSchemaValidationError(
                f"Model output is not valid JSON for {schema.__name__}: {exc}"
            ) from exc
        try:
            return schema.model_validate(parsed_json)
        except ValidationError as exc:
            raise ModelSchemaValidationError(
                f"Model output does not conform to schema {schema.__name__}: {exc}"
            ) from exc
