"""Hermes AI assistant adapter.

Thin wrapper around OpenAICompatibleAdapter with Hermes-specific defaults.
Hermes uses the standard OpenAI chat completions API format, so this adapter
composes OpenAICompatibleAdapter and provides Hermes-specific configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from benchmark.agents.openai_compatible import OpenAICompatibleAdapter

if TYPE_CHECKING:
    import httpx

    from benchmark.agents.base import AgentRequest, AgentResponse

logger = structlog.get_logger()

_HERMES_DEFAULT_MODEL = "hermes-latest"
_HERMES_VERSION = "1.0.0"


class HermesAdapter:
    """Adapter for Hermes AI assistant.

    Req 3.1: execute(request) -> response with content, optional LLM metrics, errors list.
    Req 3.2: health_check() returns True within 10s, False otherwise.
    Req 3.7: On failure, returns AgentResponse with empty content and error in errors list.

    Uses composition over inheritance: delegates all API communication to
    OpenAICompatibleAdapter with Hermes-specific configuration.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        signing_key: str | None = None,
        model: str = _HERMES_DEFAULT_MODEL,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
        input_price_per_mtok: float | None = None,
        output_price_per_mtok: float | None = None,
    ) -> None:
        self._log = logger.bind(agent_name="hermes")
        self._inner = OpenAICompatibleAdapter(
            endpoint=endpoint,
            model=model,
            agent_name="hermes",
            agent_version=_HERMES_VERSION,
            api_key=api_key,
            signing_key=signing_key,
            timeout=timeout,
            client=client,
            input_price_per_mtok=input_price_per_mtok,
            output_price_per_mtok=output_price_per_mtok,
        )
        self._log.debug("hermes_adapter_initialized", endpoint=endpoint, model=model)

    @property
    def name(self) -> str:
        """Agent name (non-empty, max 128 characters)."""
        return self._inner.name

    @property
    def version(self) -> str:
        """Agent version (non-empty, max 128 characters)."""
        return self._inner.version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute a request via Hermes endpoint.

        Delegates to OpenAICompatibleAdapter for request/response translation.
        """
        self._log.debug("hermes_execute_start", prompt_length=len(request.prompt))
        response = await self._inner.execute(request)
        self._log.debug(
            "hermes_execute_complete",
            has_errors=bool(response.errors),
            content_length=len(response.content),
        )
        return response

    async def health_check(self) -> bool:
        """Check if Hermes endpoint is reachable within 10 seconds."""
        return await self._inner.health_check()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._inner.close()
