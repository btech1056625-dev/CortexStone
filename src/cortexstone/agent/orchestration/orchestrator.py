import logging
from typing import Any

from cortexstone.agent.models.interface import ModelClient, ModelMessage, ModelRole, Role
from cortexstone.agent.orchestration.router import IntentRouter
from cortexstone.agent.schemas.actions import AgentPlan, ProposedAction
from cortexstone.agent.schemas.routing import RouteDecision

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

    async def run(self, user_message: str, context: list[dict[str, Any]]) -> list[ProposedAction]:

        # Step 1: Fast triage via Nemotron Mini Router
        try:
            route: RouteDecision = await self.router.route(user_message)
        except Exception as e:
            logger.error(f"Router failed: {e}. Defaulting to safe fallback.")
            route = RouteDecision(intent="clarification", needs_reasoner=False, complexity="low")

        # Step 2: Dispatch to Nemotron 3 Super 120B Reasoner
        # Only triggers if router says needs_reasoner OR intent is tool_action
        if route.needs_reasoner or route.intent == "tool_action":
            messages = self._build_messages(user_message, context)

            # Max 5 planning iterations enforcement
            for iteration in range(self.max_iterations):
                try:
                    response = await self.model_client.generate_for_role(
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

        formatted_ctx = []
        for c in context:
            ref = c.get("source_ref", "unknown")
            text = c.get("content", "")
            formatted_ctx.append(f"[{ref}]: {text}")

        ctx_str = "\n".join(formatted_ctx) if formatted_ctx else "No context."

        return [
            ModelMessage(
                role=Role.SYSTEM, content="You are Cortexstone. Produce a bounded AgentPlan."
            ),
            ModelMessage(role=Role.USER, content=f"Context:\n{ctx_str}\n\nTask: {prompt}"),
        ]
