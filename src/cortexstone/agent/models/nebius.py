"""
src/cortexstone/agent/models/nebius.py

Nebius Token Factory adapter supporting dual-model routing:
- Nemotron Mini (Intent & Complexity Routing)
- Nemotron 3 Super 120B A12B (Complex Reasoning & Planning)
"""

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

logger = logging.getLogger("cortexstone.agent.models.nebius")

T = TypeVar("T", bound=BaseModel)


class NebiusTokenFactoryClient(ModelClient):
    """
    Adapter for NVIDIA open models hosted on Nebius Token Factory.
    Enforces server-side bounded execution, structured outputs, and credential protection.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.tokenfactory.nebius.com/v1",
        router_model_id: str = "nvidia/nemotron-mini-4b-instruct",
        reasoner_model_id: str = "nvidia/nemotron-3-super-120b-a12b",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("Nebius API key must not be empty")

        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.router_model_id = router_model_id
        self.reasoner_model_id = reasoner_model_id
        self.model_map: dict[ModelRole, str] = {
            ModelRole.ROUTER: router_model_id,
            ModelRole.REASONER: reasoner_model_id,
        }
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
        """Dispatch inference based on model role with role-tailored defaults."""
        model_id = self.model_map.get(role, self.reasoner_model_id)

        # Adaptive bounded defaults based on model tier
        if role == ModelRole.ROUTER:
            effective_timeout = timeout if timeout is not None else 10.0
            effective_max_tokens = max_tokens if max_tokens is not None else 512
        else:
            effective_timeout = timeout if timeout is not None else 45.0
            effective_max_tokens = max_tokens if max_tokens is not None else 2048

        return await self.generate(
            messages=messages,
            schema=schema,
            model_id=model_id,
            temperature=temperature,
            max_tokens=effective_max_tokens,
            timeout=effective_timeout,
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
        chosen_model = model_id or self.reasoner_model_id

        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # If a Pydantic schema is provided, steer model towards structured JSON output
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}

        start_time = time.monotonic()
        client = self._external_client or httpx.AsyncClient()

        try:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "Inference timed out after %.1fs for model %s", timeout, chosen_model
            )
            raise ModelTimeoutError(
                f"Nebius Token Factory request timed out after {timeout:.1f}s"
            ) from exc
        except httpx.RequestError as exc:
            logger.error(
                "Network error communicating with Nebius: %s", type(exc).__name__
            )
            raise ModelError(
                f"Network error during model inference: {type(exc).__name__}"
            ) from exc
        finally:
            if not self._external_client:
                await client.aclose()

        latency_ms = (time.monotonic() - start_time) * 1000.0

        if resp.status_code in (401, 403):
            raise ModelAuthenticationError(
                "Nebius Token Factory authentication failed: invalid API key"
            )
        elif resp.status_code == 429:
            raise ModelRateLimitError(
                "Nebius Token Factory rate limit or quota exceeded (HTTP 429)"
            )
        elif resp.status_code >= 400:
            raise ModelError(f"Nebius Token Factory error (HTTP {resp.status_code})")

        data = resp.json()
        choice = data["choices"][0]
        raw_text = choice["message"].get("content", "")
        finish_reason = choice.get("finish_reason", "stop")

        usage_data = data.get("usage", {})
        usage = UsageMetadata(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            latency_ms=latency_ms,
        )

        parsed_model: T | None = None
        if schema is not None:
            parsed_model = self._parse_and_validate(raw_text, schema)

        return ModelResponse(
            raw_content=raw_text,
            parsed=parsed_model,
            model_id=chosen_model,
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _parse_and_validate(raw_text: str, schema: type[T]) -> T:
        """Strips potential Markdown formatting and validates JSON against the Pydantic schema."""
        clean_text = raw_text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if len(lines) >= 2:
                # Remove opening ```json / ``` and closing ```
                first_line = lines[0].strip()
                last_line = lines[-1].strip()
                start_idx = 1 if first_line.startswith("```") else 0
                end_idx = -1 if last_line == "```" else len(lines)
                clean_text = "\n".join(lines[start_idx:end_idx]).strip()

        try:
            parsed_json = json.loads(clean_text)
        except json.JSONDecodeError as err:
            logger.warning(
                "Model returned invalid JSON for schema %s: %s", schema.__name__, err
            )
            raise ModelSchemaValidationError(
                f"Model output is not valid JSON for {schema.__name__}: {err}"
            ) from err

        try:
            return schema.model_validate(parsed_json)
        except ValidationError as err:
            logger.warning(
                "Model output failed Pydantic validation for %s: %s",
                schema.__name__,
                err,
            )
            raise ModelSchemaValidationError(
                f"Model output does not conform to schema {schema.__name__}: {err}"
            ) from err
