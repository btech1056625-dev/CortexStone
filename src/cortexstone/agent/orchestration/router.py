"""
src/cortexstone/agent/orchestration/router.py

Intent and complexity router powered by Nemotron Mini.
Delivered by Archis Samanta (ML/DL — Agents Core) for Cortexstone.
"""

from __future__ import annotations

import logging
from cortexstone.agent.models.interface import (
    ModelClient,
    ModelRole,
    ModelMessage,
    Role,
    ModelError,
)
from cortexstone.agent.schemas.routing import (
    RouteDecision,
    IntentCategory,
    ComplexityLevel,
)
from cortexstone.agent.prompts.templates import ROUTER_SYSTEM_PROMPT_V1

logger = logging.getLogger("cortexstone.agent.orchestration.router")


class IntentRouter:
    """
    Coordinates Nemotron Mini to classify incoming requests and determine complexity.
    """

    def __init__(
        self,
        model_client: ModelClient,
        system_prompt: str = ROUTER_SYSTEM_PROMPT_V1,
    ) -> None:
        self.model_client = model_client
        self.system_prompt = system_prompt

    async def route(self, user_message: str) -> RouteDecision:
        """
        Analyze a user query using Nemotron Mini and return a typed RouteDecision.
        """
        if not user_message or not user_message.strip():
            return RouteDecision(
                intent=IntentCategory.CLARIFICATION,
                complexity=ComplexityLevel.LOW,
                needs_reasoner=False,
                extracted_entities=[],
                rationale="Empty user input received",
            )

        messages = [
            ModelMessage(role=Role.SYSTEM, content=self.system_prompt),
            ModelMessage(role=Role.USER, content=user_message.strip()),
        ]

        try:
            response = await self.model_client.generate_for_role(
                role=ModelRole.ROUTER,
                messages=messages,
                schema=RouteDecision,
            )
            if response.parsed is None:
                raise ModelError("Model failed to return parsed RouteDecision schema")
            return response.parsed
        except Exception as exc:
            logger.warning("Intent routing fallback triggered due to: %s", exc)
            # Safe default fallback: treat as clarification or route to reasoner if uncertainty exists
            return RouteDecision(
                intent=IntentCategory.CLARIFICATION,
                complexity=ComplexityLevel.MEDIUM,
                needs_reasoner=True,
                extracted_entities=[],
                rationale=f"Fallback routed due to router failure: {type(exc).__name__}",
            )
