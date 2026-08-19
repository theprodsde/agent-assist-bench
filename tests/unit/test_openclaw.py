"""Unit tests for OpenClawAdapter.

Verifies that OpenClawAdapter correctly composes OpenAICompatibleAdapter,
satisfies the AgentAdapter protocol, and applies OpenClaw-specific defaults.
"""

from __future__ import annotations

import json

import httpx
import pytest

from benchmark.agents.base import AgentAdapter, AgentRequest
from benchmark.agents.openclaw import OpenClawAdapter

# --- Helpers ---


def _make_openai_response(
    content: str = "OpenClaw says hi",
    model: str = "openclaw-v1",
    prompt_tokens: int = 12,
    completion_tokens: int = 8,
    total_tokens: int = 20,
) -> dict:
    """Build a mock OpenAI-format chat completions response."""
    return {
        "id": "chatcmpl-oc123",
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
    """Create a mock transport returning a configured response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error:
            if issubclass(raise_error, httpx.TimeoutException):
                raise raise_error("Connection timed out")
            raise raise_error("Connection failed")
        body = json.dumps(json_body).encode() if json_body else b""
        return httpx.Response(status_code=status_code, content=body)

    return httpx.MockTransport(handler)


# --- Tests ---


class TestProtocolCompliance:
    """OpenClawAdapter satisfies the AgentAdapter protocol."""

    def test_satisfies_agent_adapter_protocol(self) -> None:
        """OpenClawAdapter is recognized as an AgentAdapter instance."""
        adapter = OpenClawAdapter(endpoint="http://localhost:9000")
        assert isinstance(adapter, AgentAdapter)

    def test_name_is_openclaw(self) -> None:
        """Name property returns 'openclaw'."""
        adapter = OpenClawAdapter(endpoint="http://localhost:9000")
        assert adapter.name == "openclaw"

    def test_version_defaults(self) -> None:
        """Version defaults to '1.0.0'."""
        adapter = OpenClawAdapter(endpoint="http://localhost:9000")
        assert adapter.version == "1.0.0"

    def test_custom_version(self) -> None:
        """Version can be overridden."""
        adapter = OpenClawAdapter(endpoint="http://localhost:9000", version="2.1.0")
        assert adapter.version == "2.1.0"


class TestExecute:
    """Tests for OpenClawAdapter.execute()."""

    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        """Req 3.1: Returns AgentResponse with content and LLM metrics."""
        response_body = _make_openai_response(content="Hello from OpenClaw")
        transport = _mock_transport(json_body=response_body)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenClawAdapter(endpoint="http://localhost:9000", client=client)
        request = AgentRequest(prompt="Summarize this document")
        response = await adapter.execute(request)

        assert response.content == "Hello from OpenClaw"
        assert response.errors == []
        assert response.llm_metrics is not None
        assert response.llm_metrics.model == "openclaw-v1"
        assert response.llm_metrics.total_tokens == 20

    @pytest.mark.asyncio
    async def test_api_key_forwarded(self) -> None:
        """API key is passed through to the underlying adapter."""
        captured_headers: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            body = json.dumps(_make_openai_response()).encode()
            return httpx.Response(200, content=body)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenClawAdapter(
            endpoint="http://localhost:9000",
            api_key="oc-secret-key",
            client=client,
        )
        await adapter.execute(AgentRequest(prompt="test"))

        assert captured_headers.get("authorization") == "Bearer oc-secret-key"

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self) -> None:
        """Req 3.7: On timeout, returns empty content with error."""
        transport = _mock_transport(raise_error=httpx.ReadTimeout)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenClawAdapter(endpoint="http://localhost:9000", client=client)
        response = await adapter.execute(AgentRequest(prompt="test"))

        assert response.content == ""
        assert len(response.errors) >= 1

    @pytest.mark.asyncio
    async def test_connection_error_returns_error(self) -> None:
        """Req 3.7: On connection failure, returns empty content with error."""
        transport = _mock_transport(raise_error=httpx.ConnectError)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenClawAdapter(endpoint="http://localhost:9000", client=client)
        response = await adapter.execute(AgentRequest(prompt="test"))

        assert response.content == ""
        assert len(response.errors) >= 1


class TestHealthCheck:
    """Tests for OpenClawAdapter.health_check()."""

    @pytest.mark.asyncio
    async def test_healthy_endpoint(self) -> None:
        """Req 3.2: Returns True when endpoint responds."""
        transport = _mock_transport(status_code=200, json_body={"data": []})
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenClawAdapter(endpoint="http://localhost:9000", client=client)
        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_unreachable_endpoint(self) -> None:
        """Req 3.2: Returns False when endpoint is unreachable."""
        transport = _mock_transport(raise_error=httpx.ConnectError)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenClawAdapter(endpoint="http://localhost:9000", client=client)
        assert await adapter.health_check() is False


class TestResourceManagement:
    """Tests for client lifecycle."""

    @pytest.mark.asyncio
    async def test_close_delegates_to_inner(self) -> None:
        """close() releases the underlying client."""
        adapter = OpenClawAdapter(endpoint="http://localhost:9000")
        # Should not raise
        await adapter.close()


class TestOpenClawEndpointContract:
    """Focused coverage for OpenClaw's shared OpenAI endpoint contract."""

    @pytest.mark.asyncio
    async def test_image_and_audio_payload_preserves_content_and_metadata(self) -> None:
        """Supported standard parts retain source content and attachment metadata."""
        captured: dict = {}
        exact_content = "Exact OpenClaw response\nwith preserved spacing  "

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    **_make_openai_response(content=exact_content, model="openclaw-prod"),
                    "usage": {
                        "prompt_tokens": 31,
                        "completion_tokens": 11,
                        "total_tokens": 42,
                        "cost": 0.0075,
                    },
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenClawAdapter(
            endpoint="http://openclaw.example",
            api_key="openclaw-secret",
            model="openclaw-prod",
            version="3.2.1",
            client=client,
        )
        response = await adapter.execute(
            AgentRequest(
                prompt="Describe both inputs without changing their meaning.",
                attachments=[
                    {
                        "type": "image",
                        "filename": "diagram.png",
                        "mime_type": "image/png",
                        "size_bytes": 4,
                        "content_bytes": b"PNG!",
                    },
                    {
                        "type": "audio",
                        "filename": "note.mp3",
                        "mime_type": "audio/mpeg",
                        "size_bytes": 4,
                        "content_base64": "bXAzIQ==",
                    },
                ],
            )
        )

        assert captured["model"] == "openclaw-prod"
        assert captured["messages"][0]["content"][0] == {
            "type": "text",
            "text": "Describe both inputs without changing their meaning.",
        }
        image_part, audio_part = captured["messages"][0]["content"][1:]
        assert image_part["image_url"]["url"] == "data:image/png;base64,UE5HIQ=="
        assert image_part["metadata"] == {
            "type": "image",
            "filename": "diagram.png",
            "mime_type": "image/png",
            "size_bytes": 4,
        }
        assert audio_part["input_audio"] == {"data": "bXAzIQ==", "format": "mp3"}
        assert audio_part["metadata"] == {
            "type": "audio",
            "filename": "note.mp3",
            "mime_type": "audio/mpeg",
            "size_bytes": 4,
        }
        assert response.content == exact_content
        assert response.llm_metrics is not None
        assert response.llm_metrics.model == "openclaw-prod"
        assert response.llm_metrics.prompt_tokens == 31
        assert response.llm_metrics.completion_tokens == 11
        assert response.llm_metrics.total_tokens == 42
        assert response.llm_metrics.estimated_cost_usd == 0.0075
        assert adapter.version == "3.2.1"

    @pytest.mark.asyncio
    async def test_video_is_rejected_before_prompt_only_request(self) -> None:
        """OpenClaw has no documented video part, so video is never silently dropped."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=_make_openai_response())

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenClawAdapter(endpoint="http://openclaw.example", client=client)
        response = await adapter.execute(
            AgentRequest(
                prompt="Review this clip",
                attachments=[
                    {
                        "type": "video",
                        "filename": "clip.mp4",
                        "mime_type": "video/mp4",
                        "size_bytes": 4,
                        "content_bytes": b"MP4!",
                    }
                ],
            )
        )

        assert response.content == ""
        assert response.errors == ["unsupported_modality:video"]
        assert calls == 0

    @pytest.mark.asyncio
    async def test_api_key_is_not_returned_from_endpoint_error(self) -> None:
        """Transport errors can be returned safely without exposing the bearer key."""
        secret = "openclaw-secret"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text=f"invalid bearer token {secret}")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenClawAdapter(
            endpoint="http://openclaw.example",
            api_key=secret,
            client=client,
        )
        response = await adapter.execute(AgentRequest(prompt="test"))

        assert response.content == ""
        assert response.errors
        assert all(secret not in error for error in response.errors)
