"""Agent adapters and registry."""

from benchmark.agents.base import (
    AgentAdapter,
    AgentRequest,
    AgentResponse,
    UnsupportedModalityError,
)
from benchmark.agents.registry import AgentRegistry

__all__ = [
    "AgentAdapter",
    "AgentRequest",
    "AgentResponse",
    "UnsupportedModalityError",
    "AgentRegistry",
]
