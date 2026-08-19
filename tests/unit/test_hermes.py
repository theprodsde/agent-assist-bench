"""Unit tests for HermesAdapter.

Tests that HermesAdapter correctly composes OpenAICompatibleAdapter,
satisfies the AgentAdapter protocol, and handles Hermes-specific defaults.
"""

from __future__ import annotations

import json

import httpx
import pytest

from benchmark.agents.base import AgentAdapter, AgentRequest
from benchmark.agents.hermes import HermesAdapter

# --- Helpers ---


def _make_openai_response(
    content: str = "Hello from Hermes!",
    model: str = "hermes-latest",
    prompt_tokens: int = 12,
    completion_tokens: int = 8,
    total_tokens: int = 20,
) -> dict:
    """Build a mock OpenAI-compatible chat completions response."""
    return {
        "id": "chatcmpl-hermes-001",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }


def _mock_transport(
    status_code: int = 200,
    json_body: dict | None = None,
    raise_error: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Create a mock transport returning configured responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error:
            if issubclass(raise_error, httpx.TimeoutException):
                raise raise_error("Connection timed out")
            raise raise_error("Connection failed")
        body = json.dumps(json_body or {}).encode()
        return httpx.Response(status_code=status_code, content=body)

    return httpx.MockTransport(handler)


def _make_adapter(
    transport: httpx.MockTransport,
    api_key: str | None = "hermes-key-123",
) -> HermesAdapter:
    """Create HermesAdapter with injected mock transport."""
    return HermesAdapter(
        endpoint="http://hermes.local:8080",
        api_key=api_key,
        client=httpx.AsyncClient(transport=transport),
    )


# --- Tests ---


class TestProtocolCompliance:
    """Verify HermesAdapter satisfies the AgentAdapter protocol."""

    def test_is_agent_adapter(self) -> None:
        """HermesAdapter satisfies the AgentAdapter runtime_checkable protocol."""
        adapter = HermesAdapter(endpoint="http://localhost:8080")
        assert isinstance(adapter, AgentAdapter)

    def test_name_is_hermes(self) -> None:
        """Name property returns 'hermes'."""
        adapter = HermesAdapter(endpoint="http://localhost:8080")
        assert adapter.name == "hermes"

    def test_version_is_set(self) -> None:
        """Version property returns a non-empty version string."""
        adapter = HermesAdapter(endpoint="http://localhost:8080")
        assert adapter.version
        assert len(adapter.version) <= 128


class TestExecute:
    """Tests for HermesAdapter.execute()."""

    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        """Req 3.1: Returns AgentResponse with content and LLM metrics."""
        transport = _mock_transport(json_body=_make_openai_response())
        adapter = _make_adapter(transport)

        request = AgentRequest(prompt="Explain microservices")
        response = await adapter.execute(request)

        assert response.content == "Hello from Hermes!"
        assert response.errors == []
        assert response.llm_metrics is not None
        assert response.llm_metrics.model == "hermes-latest"
        assert response.llm_metrics.total_tokens == 20

    @pytest.mark.asyncio
    async def test_multimodal_contract_preserves_payload_and_metrics(self) -> None:
        """Hermes forwards OpenAI content parts and returns exact endpoint data."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    **_make_openai_response(content="Hermes exact response"),
                    "usage": {
                        "prompt_tokens": 15,
                        "completion_tokens": 6,
                        "total_tokens": 21,
                        "estimated_cost_usd": 0.0025,
                    },
                },
            )

        adapter = _make_adapter(httpx.MockTransport(handler), api_key="hermes-secret")
        response = await adapter.execute(
            AgentRequest(
                prompt="Compare these inputs",
                attachments=[
                    {
                        "type": "image",
                        "filename": "chart.png",
                        "mime_type": "image/png",
                        "size_bytes": 8,
                        "url": "https://cdn.example/chart.png",
                    },
                    {
                        "type": "audio",
                        "filename": "memo.wav",
                        "mime_type": "audio/wav",
                        "size_bytes": 4,
                        "content_bytes": b"WAVE",
                    },
                ],
            )
        )

        assert captured["headers"]["authorization"] == "Bearer hermes-secret"
        parts = captured["body"]["messages"][0]["content"]
        assert parts[0] == {"type": "text", "text": "Compare these inputs"}
        assert parts[1]["image_url"]["url"] == "https://cdn.example/chart.png"
        assert parts[1]["metadata"] == {
            "type": "image",
            "filename": "chart.png",
            "mime_type": "image/png",
            "size_bytes": 8,
        }
        assert parts[2]["input_audio"] == {"data": "V0FWRQ==", "format": "wav"}
        assert response.content == "Hermes exact response"
        assert response.llm_metrics is not None
        assert response.llm_metrics.total_tokens == 21
        assert response.llm_metrics.estimated_cost_usd == 0.0025

        """Req 3.7: On timeout, returns empty content with error."""
        transport = _mock_transport(raise_error=httpx.ReadTimeout)
        adapter = _make_adapter(transport)

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == ""
        assert len(response.errors) >= 1

    @pytest.mark.asyncio
    async def test_connection_failure_returns_error(self) -> None:
        """Req 3.7: On connection failure, returns empty content with error."""
        transport = _mock_transport(raise_error=httpx.ConnectError)
        adapter = _make_adapter(transport)

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == ""
        assert len(response.errors) >= 1

    @pytest.mark.asyncio
    async def test_api_key_forwarded_to_endpoint(self) -> None:
        """Authentication: API key is sent as Bearer token."""
        captured_headers: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            body = json.dumps(_make_openai_response()).encode()
            return httpx.Response(200, content=body)

        transport = httpx.MockTransport(handler)
        adapter = _make_adapter(transport, api_key="sk-hermes-secret")

        request = AgentRequest(prompt="Hello")
        await adapter.execute(request)

        assert captured_headers.get("authorization") == "Bearer sk-hermes-secret"


class TestHealthCheck:
    """Tests for HermesAdapter.health_check()."""

    @pytest.mark.asyncio
    async def test_healthy_endpoint(self) -> None:
        """Req 3.2: Returns True when endpoint responds."""
        transport = _mock_transport(status_code=200, json_body={"data": []})
        adapter = _make_adapter(transport)

        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_unreachable_endpoint(self) -> None:
        """Req 3.2: Returns False when endpoint is unreachable."""
        transport = _mock_transport(raise_error=httpx.ConnectError)
        adapter = _make_adapter(transport)

        assert await adapter.health_check() is False


class TestCustomConfiguration:
    """Tests for Hermes-specific configuration."""

    def test_custom_model(self) -> None:
        """Adapter can be configured with a custom model."""
        adapter = HermesAdapter(
            endpoint="http://localhost:8080",
            model="hermes-v2-pro",
        )
        # Model is passed to inner adapter — verify name/version are still correct
        assert adapter.name == "hermes"

    @pytest.mark.asyncio
    async def test_close_delegates(self) -> None:
        """close() delegates to the inner adapter without error."""
        adapter = HermesAdapter(endpoint="http://localhost:8080")
        await adapter.close()  # Should not raise
