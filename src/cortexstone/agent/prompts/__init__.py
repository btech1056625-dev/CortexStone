"""
src/cortexstone/agent/prompts/__init__.py

Prompt assets for Cortexstone models.
"""
from cortexstone.agent.prompts.templates import (
    ROUTER_SYSTEM_PROMPT_V1,
    REASONER_SYSTEM_PROMPT_V1,
    MEMORY_RECALL_PROMPT_V1,
)

__all__ = [
    "ROUTER_SYSTEM_PROMPT_V1",
    "REASONER_SYSTEM_PROMPT_V1",
    "MEMORY_RECALL_PROMPT_V1",
]
