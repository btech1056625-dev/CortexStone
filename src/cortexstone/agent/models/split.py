"""Composite model client that routes Groq and Google AI Studio requests by role."""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import BaseModel

from cortexstone.agent.models.interface import (
    ModelClient,
    ModelError,
    ModelMessage,
    ModelResponse,
    ModelRole,
)
from cortexstone.agent.models.openai_compatible import OpenAICompatibleClient

T = TypeVar("T", bound=BaseModel)


class SplitModelClient(ModelClient):
    def __init__(
        self,
        groq_api_key: str,
        groq_model_id: str,
        google_api_key: str | None = None,
        google_model_id: str = "gemini-2.5-flash",
        groq_base_url: str = "https://api.groq.com/openai/v1",
        google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai",
        router_client: httpx.AsyncClient | None = None,
        reasoner_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.router = OpenAICompatibleClient(
            api_key=groq_api_key,
            base_url=groq_base_url,
            model_id=groq_model_id,
            provider_name="Groq",
            client=router_client,
        )
        self.reasoner = (
            OpenAICompatibleClient(
                api_key=google_api_key,
                base_url=google_base_url,
                model_id=google_model_id,
                provider_name="Google AI Studio",
                client=reasoner_client,
            )
            if google_api_key is not None
            else None
        )

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
        client = self.router if role == ModelRole.ROUTER else self.reasoner
        if client is None:
            raise ModelError("Google AI Studio is required for reasoning but is not configured.")
        return await client.generate_for_role(
            role=role,
            messages=messages,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
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
        if self.reasoner is None:
            raise ModelError("Google AI Studio is required for reasoning but is not configured.")
        return await self.reasoner.generate(
            messages=messages,
            schema=schema,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
