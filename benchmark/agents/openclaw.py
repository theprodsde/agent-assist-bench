"""OpenClaw agent adapter.

Thin wrapper around OpenAICompatibleAdapter for the OpenClaw AI assistant.
Uses composition to delegate all OpenAI-compatible protocol handling while
providing OpenClaw-specific defaults (name, version, model, logging context).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from benchmark.agents.openai_compatible import OpenAICompatibleAdapter
from benchmark.models.domain import InputType

_OPENCLAW_DEFAULT_MODEL = "openclaw"
_OPENCLAW_VERSION = "1.0.0"
# OpenClaw currently follows the shared image_url/input_audio contract.  It
# has no documented OpenAI-compatible video content part, so video must be
# rejected before a prompt-only request can be sent.
_OPENCLAW_SUPPORTED_MODALITIES = frozenset({InputType.IMAGE, InputType.AUDIO})

if TYPE_CHECKING:
    import httpx

    from benchmark.agents.base import AgentRequest, AgentResponse

logger = structlog.get_logger()


class OpenClawAdapter:
    """Adapter for OpenClaw AI assistant.

    Composes OpenAICompatibleAdapter since OpenClaw exposes a standard
    OpenAI chat completions endpoint. This class adds OpenClaw-specific
    identity, defaults, and structured logging context.

    Req 3.1: execute(request) -> response with content, optional LLM metrics, errors list.
    Req 3.2: health_check() returns True within 10s, False otherwise.
    Req 3.7: On failure, returns AgentResponse with empty content and error in errors list.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        signing_key: str | None = None,
        model: str = _OPENCLAW_DEFAULT_MODEL,
        version: str = _OPENCLAW_VERSION,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._inner = OpenAICompatibleAdapter(
            endpoint=endpoint,
            model=model,
            agent_name="openclaw",
            agent_version=version,
            api_key=api_key,
            signing_key=signing_key,
            timeout=timeout,
            client=client,
            supported_modalities=set(_OPENCLAW_SUPPORTED_MODALITIES),
        )
        self._log = logger.bind(agent_name="openclaw")

    @property
    def name(self) -> str:
        """Agent name (non-empty, max 128 characters)."""
        return self._inner.name

    @property
    def version(self) -> str:
        """Agent version (non-empty, max 128 characters)."""
        return self._inner.version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute request via OpenClaw's OpenAI-compatible endpoint.

        Req 3.1: Returns AgentResponse with content, optional LLM metrics, errors list.
        Req 3.7: On failure, content is empty and errors list has at least one entry.
        """
        self._log.debug("openclaw_execute_start", prompt_length=len(request.prompt))
        response = await self._inner.execute(request)
        self._log.debug(
            "openclaw_execute_complete",
            content_length=len(response.content),
            has_errors=bool(response.errors),
        )
        return response

    async def health_check(self) -> bool:
        """Check if OpenClaw endpoint is reachable within 10 seconds.

        Req 3.2: Returns True if responds within 10s, False otherwise.
        """
        healthy = await self._inner.health_check()
        if not healthy:
            self._log.warning("openclaw_health_check_failed")
        return healthy

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._inner.close()
