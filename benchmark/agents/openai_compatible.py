"""OpenAI-compatible agent adapter.

Translates between AgentRequest/AgentResponse and the OpenAI chat completions
API format. Supports any endpoint that implements the OpenAI API contract
(e.g., vLLM, Ollama, Azure OpenAI, LiteLLM).
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import structlog

from benchmark.agents.base import AgentRequest, AgentResponse, UnsupportedModalityError
from benchmark.models.domain import Attachment, InputType, LLMMetrics

logger = structlog.get_logger()


class OpenAICompatibleAdapter:
    """Adapter for any OpenAI-compatible chat completions endpoint.

    Req 3.1: execute(request) -> response with content, optional LLM metrics, errors list.
    Req 3.2: health_check() returns True within 10s, False otherwise.
    Req 3.7: On failure, returns AgentResponse with empty content and error in errors list.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        agent_name: str = "openai-compatible",
        agent_version: str = "1.0.0",
        api_key: str | None = None,
        signing_key: str | None = None,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
        supported_modalities: set[InputType] | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._name = agent_name
        self._version = agent_version
        self._api_key = api_key
        self._signing_key = signing_key
        self._timeout = timeout
        self._supported_modalities = (
            set(supported_modalities)
            if supported_modalities is not None
            else {InputType.IMAGE, InputType.AUDIO}
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._log = logger.bind(
            agent_name=self._name,
            endpoint=self._endpoint,
            deployment_type="openai_compatible",
        )

    @property
    def name(self) -> str:
        """Agent name (non-empty, max 128 characters)."""
        return self._name

    @property
    def version(self) -> str:
        """Agent version (non-empty, max 128 characters)."""
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Translate AgentRequest to OpenAI chat completions format and parse response.

        Req 3.1: Returns AgentResponse with content, optional LLM metrics, errors list.
        Req 3.7: On failure, content is empty and errors list has at least one entry.
        """
        payload, unsupported_modality = self._build_payload(request)
        if unsupported_modality is not None:
            error = UnsupportedModalityError(modality=unsupported_modality).as_error()
            self._log.warning(
                "openai_request_unsupported_modality",
                modality=unsupported_modality.value,
            )
            return AgentResponse(content="", errors=[error])

        self._log.debug("openai_request_sent", model=self._model)

        body_bytes = json.dumps(payload).encode("utf-8")
        headers = self._build_headers(body=body_bytes)

        try:
            response = await self._client.post(
                f"{self._endpoint}/chat/completions",
                content=body_bytes,
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            self._log.error("openai_request_timeout", error=self._redact(str(exc)))
            return AgentResponse(
                content="",
                errors=[f"Request timed out: {self._redact(str(exc))}"],
            )
        except httpx.HTTPStatusError as exc:
            unsupported_modality = self._extract_unsupported_modality(exc.response, request)
            if unsupported_modality is not None:
                error = UnsupportedModalityError(modality=unsupported_modality).as_error()
                self._log.warning(
                    "openai_request_rejected_modality",
                    modality=unsupported_modality.value,
                    status_code=exc.response.status_code,
                )
                return AgentResponse(content="", errors=[error])
            self._log.error(
                "openai_request_http_error",
                status_code=exc.response.status_code,
                error=self._redact(str(exc)),
            )
            return AgentResponse(
                content="",
                errors=[
                    f"HTTP error {exc.response.status_code}: {self._redact(exc.response.text)}"
                ],
            )
        except httpx.HTTPError as exc:
            self._log.error("openai_request_failed", error=self._redact(str(exc)))
            return AgentResponse(
                content="",
                errors=[f"Communication failure: {self._redact(str(exc))}"],
            )

        try:
            data = response.json()
            unsupported_modality = self._extract_unsupported_modality_data(data, request)
            if unsupported_modality is not None:
                error = UnsupportedModalityError(modality=unsupported_modality).as_error()
                return AgentResponse(content="", errors=[error])
            content = data["choices"][0]["message"]["content"]
            if content is None:
                content = ""
            llm_metrics = self._extract_metrics(data)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._log.error("openai_response_parse_error", error=self._redact(str(exc)))
            return AgentResponse(
                content="",
                errors=[f"Failed to parse response: {self._redact(str(exc))}"],
            )

        self._log.debug("openai_response_received", content_length=len(content))

        return AgentResponse(content=content, llm_metrics=llm_metrics)

    def _build_payload(self, request: AgentRequest) -> tuple[dict[str, Any], InputType | None]:
        """Build a deterministic OpenAI multimodal chat-completion payload.

        Plain requests retain the legacy string content shape. Multimodal
        requests use the standard image_url and input_audio content parts;
        metadata is carried beside each part so connectors do not lose it.
        """
        if not request.attachments:
            return {
                "model": self._model,
                "messages": [{"role": "user", "content": request.prompt}],
            }, None

        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for attachment in request.attachments:
            if attachment.type not in self._supported_modalities:
                return {}, attachment.type
            part = self._build_attachment_part(attachment)
            if part is None:
                return {}, attachment.type
            content.append(part)

        return {
            "model": self._model,
            "messages": [{"role": "user", "content": content}],
        }, None

    def _build_attachment_part(self, attachment: Attachment) -> dict[str, Any] | None:
        """Convert one attachment to a standard OpenAI content part."""
        metadata = {
            "type": attachment.type.value,
            "filename": attachment.filename,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
        }
        if attachment.type == InputType.IMAGE:
            source = self._attachment_data_uri_or_url(attachment)
            if source is None:
                return None
            return {"type": "image_url", "image_url": {"url": source}, "metadata": metadata}

        if attachment.type == InputType.AUDIO:
            encoded = self._attachment_base64(attachment)
            if encoded is None:
                return None
            return {
                "type": "input_audio",
                "input_audio": {
                    "data": encoded,
                    "format": self._audio_format(attachment),
                },
                "metadata": metadata,
            }

        return None

    def _attachment_data_uri_or_url(self, attachment: Attachment) -> str | None:
        """Return an image URL or a MIME-qualified data URI."""
        if attachment.url:
            return attachment.url
        encoded = self._attachment_base64(attachment)
        if encoded is None or not attachment.mime_type:
            return None
        return f"data:{attachment.mime_type};base64,{encoded}"

    def _attachment_base64(self, attachment: Attachment) -> str | None:
        """Return attachment bytes in the endpoint's base64 representation."""
        if attachment.content_base64 is not None:
            return attachment.content_base64
        if attachment.content_bytes is not None:
            return base64.b64encode(attachment.content_bytes).decode("ascii")
        legacy_content = (attachment.model_extra or {}).get("content")
        if isinstance(legacy_content, bytes):
            return base64.b64encode(legacy_content).decode("ascii")
        if isinstance(legacy_content, str):
            return legacy_content
        return None

    def _audio_format(self, attachment: Attachment) -> str:
        """Choose the OpenAI input_audio format from MIME or filename."""
        if attachment.filename and "." in attachment.filename:
            suffix = attachment.filename.rsplit(".", 1)[1].lower()
            if suffix in {"mp3", "wav", "ogg", "flac", "webm", "mp4"}:
                return suffix
        mime_subtype = (attachment.mime_type or "audio/wav").split("/", 1)[-1].lower()
        return {"mpeg": "mp3", "x-wav": "wav"}.get(mime_subtype, mime_subtype)

    def _extract_unsupported_modality(
        self, response: httpx.Response, request: AgentRequest
    ) -> InputType | None:
        """Identify an endpoint-declared unsupported modality response."""
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text}
        return self._extract_unsupported_modality_data(data, request)

    def _extract_unsupported_modality_data(
        self, data: Any, request: AgentRequest
    ) -> InputType | None:
        """Normalize common OpenAI error shapes to the stable error contract."""
        error_payload = data.get("error") if isinstance(data, dict) else data
        serialized = str(error_payload).lower()
        if "unsupported" not in serialized and "not support" not in serialized:
            return None
        for attachment in request.attachments:
            if attachment.type.value in serialized:
                return attachment.type
        multimodal = [a.type for a in request.attachments if a.type in self._supported_modalities]
        return multimodal[0] if len(multimodal) == 1 else None

    def _redact(self, value: str) -> str:
        """Remove the configured API key from logs and persisted errors."""
        if self._api_key:
            return value.replace(self._api_key, "[REDACTED]")
        return value

    async def health_check(self) -> bool:
        """Check if the endpoint is reachable within 10 seconds.

        Req 3.2: Returns True if responds within 10s, False otherwise.
        """
        try:
            response = await self._client.get(
                f"{self._endpoint}/models",
                headers=self._build_headers(),
                timeout=10.0,
            )
            healthy = response.status_code < 500
        except httpx.HTTPError as exc:
            self._log.warning("health_check_failed", error=self._redact(str(exc)))
            healthy = False

        return healthy

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()

    def _build_headers(self, body: bytes | None = None) -> dict[str, str]:
        """Build request headers including authorization and optional request signing."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self._signing_key and body is not None:
            from benchmark.auth.signer import RequestSigner

            signer = RequestSigner(self._signing_key)
            headers.update(signer.sign(body))
        return headers

    def _extract_metrics(self, data: dict[str, Any]) -> LLMMetrics | None:
        """Extract model, token, and cost metrics from an OpenAI response."""
        usage = data.get("usage") or {}
        model = data.get("model") or self._model
        cost = usage.get("estimated_cost_usd", usage.get("cost"))
        if cost is None:
            cost = data.get("estimated_cost_usd", data.get("cost_usd", data.get("cost")))

        if not usage and not model and cost is None:
            return None

        return LLMMetrics(
            model=model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            estimated_cost_usd=cost,
        )
