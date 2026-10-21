import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from cortexstone.agent.models.interface import (
    ModelClient,
    ModelRole,
    Role,
    ModelMessage,
    ModelTimeoutError,
    ModelSchemaValidationError,
    ModelRateLimitError,
    ModelAuthenticationError,
    ModelError
)
# Importing the schema that you and Archis already created
from cortexstone.agent.schemas.actions import AgentPlan

logger = logging.getLogger(__name__)

class AgentResult(BaseModel):
    """Result returned by the AgentOrchestrator to Bhavya's backend boundary."""
    plan: Optional[AgentPlan] = None
    sources: List[str] = Field(default_factory=list)
    model_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    is_error: bool = False
    error_message: Optional[str] = None


class AgentOrchestrator:
    """
    Core Agent Orchestrator.
    Executes the request-to-model workflow using Archis's ModelClient.
    """

    def __init__(
        self,
        model_client: ModelClient,
        max_retries: int = 2,
        timeout_seconds: float = 30.0
    ):
        self.model_client = model_client
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        user_prompt: str,
        bounded_context: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None
    ) -> AgentResult:
        
        context_str = self._format_context(bounded_context)
        messages = self._build_messages(user_prompt, context_str, system_instruction)

        for attempt in range(1, self.max_retries + 2):
            try:
                # Ask the model to generate a plan matching the AgentPlan schema
                response = await self.model_client.generate_for_role(
                    role=ModelRole.REASONER,
                    messages=messages,
                    schema=AgentPlan,
                    timeout=self.timeout_seconds
                )
                
                parsed_plan: AgentPlan = response.parsed
                extracted_sources = [
                    item.get("source_ref") for item in (bounded_context or []) if "source_ref" in item
                ]

                return AgentResult(
                    plan=parsed_plan,
                    sources=extracted_sources,
                    model_id=response.model_id,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    latency_ms=response.usage.latency_ms
                )
            
            except ModelTimeoutError:
                if attempt > self.max_retries:
                    return AgentResult(is_error=True, error_message="Model inference timed out.")
            except ModelSchemaValidationError:
                if attempt > self.max_retries:
                    return AgentResult(is_error=True, error_message="Model failed to produce a valid AgentPlan.")
            except ModelRateLimitError:
                if attempt > self.max_retries:
                    return AgentResult(is_error=True, error_message="Service is currently rate limited.")
            except ModelAuthenticationError:
                return AgentResult(is_error=True, error_message="Internal model authentication failed.")
            except ModelError as err:
                return AgentResult(is_error=True, error_message=f"Model execution error: {str(err)}")

        return AgentResult(is_error=True, error_message="Maximum retries exceeded.")

    def _format_context(self, context: Optional[List[Dict[str, Any]]]) -> str:
        if not context:
            return "No prior memory context available."
        formatted = []
        for idx, item in enumerate(context, 1):
            source = item.get("source_ref", "unknown")
            content = item.get("content", "")
            formatted.append(f"[{idx}] (Source: {source}): {content}")
        return "\n".join(formatted)

    def _build_messages(self, prompt: str, context: str, custom_instruction: Optional[str]) -> List[ModelMessage]:
        base_system = (
            "You are Cortexstone, a private developer assistant.\n"
            "SYSTEM INVARIANT: You CANNOT execute tools directly. "
            "You MUST propose a structured AgentPlan containing up to 5 actions. "
            "Do not pretend an action was executed."
        )
        if custom_instruction:
            base_system += f"\n{custom_instruction}"

        return [
            ModelMessage(role=Role.SYSTEM, content=base_system),
            ModelMessage(role=Role.USER, content=f"Context:\n{context}\n\nTask: {prompt}")
        ]