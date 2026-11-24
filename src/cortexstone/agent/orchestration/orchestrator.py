import logging
from typing import Any
from xml.sax.saxutils import escape

from cortexstone.agent.models.interface import (
    ModelClient,
    ModelMessage,
    ModelResponse,
    ModelRole,
    Role,
    T,
)
from cortexstone.agent.orchestration.router import IntentRouter
from cortexstone.agent.prompts.templates import REASONER_SYSTEM_PROMPT_V1
from cortexstone.agent.schemas.actions import AgentPlan, ProposedAction
from cortexstone.agent.schemas.routing import IntentCategory, RouteDecision
from cortexstone.security.redaction import redact_secrets

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Core Agent Orchestrator.
    Wires IntentRouter and bounded execution limits per team integration specs.
    """

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client
        # 1. Wire the Intent Router
        self.router = IntentRouter(model_client)

        # 3. Enforce Bounded Execution Limits (Hard caps in code)
        self.max_iterations = 5
        self.max_tools_per_turn = 3
        self.timeout_seconds = 30.0

    async def generate_structured_response(
        self,
        messages: list[ModelMessage],
        schema: type[T],
        *,
        role: ModelRole = ModelRole.REASONER,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float = 30.0,
    ) -> ModelResponse[T]:
        """Invoke the selected agent model and return its schema-validated response."""
        safe_messages = [
            ModelMessage(
                role=message.role,
                content=redact_secrets(message.content),
                name=redact_secrets(message.name) if message.name is not None else None,
            )
            for message in messages
        ]
        return await self.model_client.generate_for_role(
            role=role,
            messages=safe_messages,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def generate_chat_response(
        self,
        user_message: str,
        messages: list[ModelMessage],
        schema: type[T],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        timeout: float = 30.0,
    ) -> ModelResponse[T]:
        """Route simple conversation to Groq and reasoning work to Google."""
        route = await self.router.route(user_message)
        role = (
            ModelRole.ROUTER
            if (
                route.intent == IntentCategory.DIRECT_CHAT
                and route.complexity == "low"
                and not route.needs_reasoner
            )
            else ModelRole.REASONER
        )
        logger.debug(
            "Chat routed to %s (intent=%s, complexity=%s)",
            role.value,
            route.intent.value,
            route.complexity.value,
        )
        return await self.generate_structured_response(
            role=role,
            messages=messages,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def run(self, user_message: str, context: list[dict[str, Any]]) -> list[ProposedAction]:

        # Step 1: Fast triage via the configured routing model
        try:
            route: RouteDecision = await self.router.route(user_message)
        except Exception as e:
            logger.error(f"Router failed: {e}. Defaulting to safe fallback.")
            route = RouteDecision(intent="clarification", needs_reasoner=False, complexity="low")

        # Step 2: Dispatch to the configured reasoning model
        # Only triggers if router says needs_reasoner OR intent is tool_action
        if route.needs_reasoner or route.intent == "tool_action":
            messages = self._build_messages(user_message, context)

            # Max 5 planning iterations enforcement
            for iteration in range(self.max_iterations):
                try:
                    response = await self.generate_structured_response(
                        role=ModelRole.REASONER,
                        messages=messages,
                        schema=AgentPlan,
                        timeout=self.timeout_seconds,
                    )
                except Exception as e:
                    logger.error(f"Reasoner execution failed on iter {iteration}: {e}")
                    break

                if not response.parsed or not response.parsed.actions:
                    return []

                proposed_actions: list[ProposedAction] = response.parsed.actions

                # Max 3 tool proposals per turn enforcement
                if len(proposed_actions) > self.max_tools_per_turn:
                    logger.warning("Tool proposal limit exceeded. Truncating to 3.")
                    proposed_actions = proposed_actions[: self.max_tools_per_turn]

                # Returning the typed ProposedAction list for the PolicyEngine
                return proposed_actions

            logger.warning("Max 5 planning iterations exhausted.")
            return []

        return []

    def _build_messages(self, prompt: str, context: list[dict[str, Any]]) -> list[ModelMessage]:
        context_items = []
        for c in context:
            ref = c.get("source_ref", "unknown")
            text = c.get("content", "")
            context_items.append(
                "<item>\n"
                f"<source_ref>{escape(str(ref))}</source_ref>\n"
                f"<content>{escape(str(text))}</content>\n"
                "</item>"
            )

        external_context = "\n".join(context_items) or "No external context provided."
        prompt_payload = (
            "<agent_input>\n"
            f"<external_context>\n{external_context}\n</external_context>\n"
            f"<user_task>{escape(prompt)}</user_task>\n"
            "</agent_input>"
        )

        return [
            ModelMessage(role=Role.SYSTEM, content=REASONER_SYSTEM_PROMPT_V1),
            ModelMessage(role=Role.USER, content=prompt_payload),
        ]
