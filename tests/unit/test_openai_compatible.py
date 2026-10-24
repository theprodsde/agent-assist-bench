"""Unit tests for OpenAICompatibleAdapter.

Tests request/response translation, health check, error handling,
and LLM metrics extraction using httpx mock transport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from benchmark.agents.base import AgentRequest
from benchmark.agents.openai_compatible import OpenAICompatibleAdapter
from benchmark.models.domain import InputType

# --- Helpers ---


def _make_openai_response(
    content: str = "Hello!",
    model: str = "gpt-4",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int = 15,
) -> dict:
    """Build a mock OpenAI chat completions response body."""
    return {
        "id": "chatcmpl-abc123",
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
    text_body: str = "",
    raise_error: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Create a mock transport that returns the configured response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if raise_error:
            # httpx error classes require a message argument
            if issubclass(raise_error, httpx.TimeoutException):
                raise raise_error("Connection timed out")
            elif issubclass(raise_error, httpx.HTTPError):
                raise raise_error("Connection failed")
            else:
                raise raise_error()
        body = json.dumps(json_body).encode() if json_body else text_body.encode()
        return httpx.Response(status_code=status_code, content=body)

    return httpx.MockTransport(handler)


# --- Tests ---


class TestExecute:
    """Tests for OpenAICompatibleAdapter.execute()."""

    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        """Req 3.1: Returns AgentResponse with content and LLM metrics."""
        response_body = _make_openai_response(content="Test response", model="gpt-4")
        transport = _mock_transport(json_body=response_body)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        request = AgentRequest(prompt="Hello, how are you?")
        response = await adapter.execute(request)

        assert response.content == "Test response"
        assert response.errors == []
        assert response.llm_metrics is not None
        assert response.llm_metrics.model == "gpt-4"
        assert response.llm_metrics.prompt_tokens == 10
        assert response.llm_metrics.completion_tokens == 5
        assert response.llm_metrics.total_tokens == 15

    @pytest.mark.asyncio
    async def test_multimodal_payload_preserves_prompt_metadata_and_content(self) -> None:
        """Image and audio use deterministic OpenAI content parts without data loss."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    **_make_openai_response(content="Exact multimodal response"),
                    "usage": {
                        "prompt_tokens": 21,
                        "completion_tokens": 7,
                        "total_tokens": 28,
                        "cost": 0.0042,
                    },
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="hermes-latest",
            client=client,
        )
        request = AgentRequest(
            prompt="Describe both attachments exactly.",
            attachments=[
                {
                    "type": InputType.IMAGE,
                    "filename": "diagram.png",
                    "mime_type": "image/png",
                    "size_bytes": 4,
                    "content_bytes": b"PNG!",
                },
                {
                    "type": InputType.AUDIO,
                    "filename": "note.mp3",
                    "mime_type": "audio/mpeg",
                    "size_bytes": 4,
                    "content_base64": "bXAzIQ==",
                },
            ],
        )

        response = await adapter.execute(request)

        parts = captured["messages"][0]["content"]
        assert parts[0] == {"type": "text", "text": request.prompt}
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"] == "data:image/png;base64,UE5HIQ=="
        assert parts[1]["metadata"] == {
            "type": "image",
            "filename": "diagram.png",
            "mime_type": "image/png",
            "size_bytes": 4,
        }
        assert parts[2]["type"] == "input_audio"
        assert parts[2]["input_audio"] == {"data": "bXAzIQ==", "format": "mp3"}
        assert parts[2]["metadata"]["filename"] == "note.mp3"
        assert response.content == "Exact multimodal response"
        assert response.llm_metrics is not None
        assert response.llm_metrics.total_tokens == 28
        assert response.llm_metrics.estimated_cost_usd == 0.0042

    @pytest.mark.asyncio
    async def test_url_image_is_sent_without_replacing_attachment_metadata(self) -> None:
        """Image URLs remain URLs and retain their source metadata."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, json=_make_openai_response(content="url response"))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080", model="hermes", client=client
        )
        await adapter.execute(
            AgentRequest(
                prompt="Review this image",
                attachments=[
                    {
                        "type": "image",
                        "filename": "remote.png",
                        "mime_type": "image/png",
                        "size_bytes": 9,
                        "url": "https://cdn.example/remote.png",
                    }
                ],
            )
        )

        part = captured["messages"][0]["content"][1]
        assert part["image_url"]["url"] == "https://cdn.example/remote.png"
        assert part["metadata"]["size_bytes"] == 9

    @pytest.mark.asyncio
    async def test_unsupported_video_returns_explicit_error_without_request(self) -> None:
        """Video is not part of the OpenAI chat content contract and is never dropped."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json=_make_openai_response())

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080", model="hermes", client=client
        )
        response = await adapter.execute(
            AgentRequest(
                prompt="Watch this clip",
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
    async def test_endpoint_modality_rejection_uses_canonical_error(self) -> None:
        """A Hermes/OpenAI endpoint rejection is an explicit failed response."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "unsupported_modality",
                        "message": "image input is not supported",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="hermes",
            client=client,
        )
        response = await adapter.execute(
            AgentRequest(
                prompt="Review this",
                attachments=[
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "content_base64": "aW1hZ2U=",
                    }
                ],
            )
        )

        assert response.content == ""
        assert response.errors == ["unsupported_modality:image"]

    @pytest.mark.asyncio
    async def test_timeout_returns_error_response(self) -> None:
        """Req 3.7: On timeout, returns empty content with error in errors list."""
        transport = _mock_transport(raise_error=httpx.ReadTimeout)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == ""
        assert len(response.errors) >= 1
        assert "timed out" in response.errors[0].lower() or "timeout" in response.errors[0].lower()

    @pytest.mark.asyncio
    async def test_http_error_returns_error_response(self) -> None:
        """Req 3.7: On HTTP error, returns empty content with error in errors list."""
        transport = _mock_transport(status_code=500, text_body="Internal Server Error")
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == ""
        assert len(response.errors) >= 1
        assert "500" in response.errors[0]

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_response(self) -> None:
        """Req 3.7: On connection failure, returns empty content with error."""
        transport = _mock_transport(raise_error=httpx.ConnectError)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == ""
        assert len(response.errors) >= 1
        assert "communication failure" in response.errors[0].lower()

    @pytest.mark.asyncio
    async def test_malformed_response_returns_error(self) -> None:
        """Req 3.7: Malformed JSON response results in error."""
        transport = _mock_transport(json_body={"invalid": "structure"})
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == ""
        assert len(response.errors) >= 1
        assert "parse" in response.errors[0].lower()

    @pytest.mark.asyncio
    async def test_response_without_usage_still_returns_metrics(self) -> None:
        """Metrics extraction handles missing usage gracefully."""
        response_body = {
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
        }
        transport = _mock_transport(json_body=response_body)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        request = AgentRequest(prompt="Hello")
        response = await adapter.execute(request)

        assert response.content == "hi"
        assert response.errors == []
        assert response.llm_metrics is not None
        assert response.llm_metrics.model == "gpt-4"
        assert response.llm_metrics.prompt_tokens is None

    @pytest.mark.asyncio
    async def test_cost_computed_from_configured_prices(self) -> None:
        """When the endpoint reports no cost, configured $/1M-token prices apply."""
        transport = _mock_transport(
            json_body=_make_openai_response(prompt_tokens=1000, completion_tokens=500)
        )
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
            input_price_per_mtok=2.0,
            output_price_per_mtok=8.0,
        )

        response = await adapter.execute(AgentRequest(prompt="Hello"))

        assert response.llm_metrics is not None
        # 1000/1M * $2 + 500/1M * $8 = 0.002 + 0.004
        assert response.llm_metrics.estimated_cost_usd == pytest.approx(0.006)

    @pytest.mark.asyncio
    async def test_endpoint_reported_cost_takes_precedence_over_prices(self) -> None:
        """A cost field reported by the endpoint wins over configured prices."""
        body = _make_openai_response(prompt_tokens=1000, completion_tokens=500)
        body["usage"]["estimated_cost_usd"] = 0.5
        transport = _mock_transport(json_body=body)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
            input_price_per_mtok=2.0,
            output_price_per_mtok=8.0,
        )

        response = await adapter.execute(AgentRequest(prompt="Hello"))

        assert response.llm_metrics is not None
        assert response.llm_metrics.estimated_cost_usd == 0.5

    @pytest.mark.asyncio
    async def test_no_prices_and_no_reported_cost_leaves_cost_none(self) -> None:
        """Without prices or an endpoint-reported cost, cost stays None."""
        transport = _mock_transport(json_body=_make_openai_response())
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        response = await adapter.execute(AgentRequest(prompt="Hello"))

        assert response.llm_metrics is not None
        assert response.llm_metrics.estimated_cost_usd is None

    @pytest.mark.asyncio
    async def test_api_key_sent_in_header(self) -> None:
        """Authorization header is set when API key is provided."""
        captured_headers: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            body = json.dumps(_make_openai_response()).encode()
            return httpx.Response(200, content=body)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            api_key="sk-test-key",
            client=client,
        )

        request = AgentRequest(prompt="Hello")
        await adapter.execute(request)

        assert captured_headers.get("authorization") == "Bearer sk-test-key"


class TestHealthCheck:
    """Tests for OpenAICompatibleAdapter.health_check()."""

    @pytest.mark.asyncio
    async def test_healthy_endpoint(self) -> None:
        """Req 3.2: Returns True when endpoint responds within 10s."""
        transport = _mock_transport(status_code=200, json_body={"data": []})
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy_endpoint_500(self) -> None:
        """Req 3.2: Returns False when endpoint returns 5xx."""
        transport = _mock_transport(status_code=500, text_body="error")
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_unreachable_endpoint(self) -> None:
        """Req 3.2: Returns False when endpoint is unreachable."""
        transport = _mock_transport(raise_error=httpx.ConnectError)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self) -> None:
        """Req 3.2: Returns False when health check times out."""
        transport = _mock_transport(raise_error=httpx.ReadTimeout)
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_4xx_is_considered_healthy(self) -> None:
        """A 4xx response means the server is up (e.g., 401 unauthorized)."""
        transport = _mock_transport(status_code=401, text_body="Unauthorized")
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )

        assert await adapter.health_check() is True


class TestProperties:
    """Tests for adapter properties."""

    def test_name_property(self) -> None:
        """Name property returns configured name."""
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            agent_name="hermes",
        )
        assert adapter.name == "hermes"

    def test_version_property(self) -> None:
        """Version property returns configured version."""
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            agent_version="2.0.0",
        )
        assert adapter.version == "2.0.0"

    def test_default_name_and_version(self) -> None:
        """Defaults for name and version are sensible."""
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
        )
        assert adapter.name == "openai-compatible"
        assert adapter.version == "1.0.0"


class TestResourceManagement:
    """Tests for client lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_owned_client(self) -> None:
        """When adapter owns the client, close() shuts it down."""
        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
        )
        # Should not raise
        await adapter.close()

    @pytest.mark.asyncio
    async def test_injected_client_not_closed(self) -> None:
        """When client is injected, close() does not close it."""
        transport = _mock_transport(json_body=_make_openai_response())
        client = httpx.AsyncClient(transport=transport)

        adapter = OpenAICompatibleAdapter(
            endpoint="http://localhost:8080",
            model="gpt-4",
            client=client,
        )
        await adapter.close()

        # Client should still be usable after adapter.close()
        assert not client.is_closed
        await client.aclose()
