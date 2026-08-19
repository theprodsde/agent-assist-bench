"""Unit tests for the framework-neutral Discord inbound connector."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benchmark.connectors.discord import (
    DiscordConnector,
    InMemoryDiscordIdempotency,
)
from benchmark.models.domain import (
    DeploymentMetrics,
    DeploymentType,
    Execution,
    ExecutionResult,
    InputType,
)


class AttachmentClient:
    """SDK-free Discord attachment client test double."""

    def __init__(self, files: dict[str, bytes | None], urls: dict[str, str] | None = None):
        self.files = files
        self.urls = urls or {}

    async def download_bytes(self, attachment):
        return self.files.get(attachment.id)

    async def resolve_url(self, attachment):
        return self.urls.get(attachment.id)


class Runner:
    def __init__(self) -> None:
        self.benchmarks = []

    async def run(self, benchmark) -> None:
        self.benchmarks.append(benchmark)


class Storage:
    def __init__(self) -> None:
        self.benchmarks = []

    async def save_benchmark(self, benchmark) -> None:
        self.benchmarks.append(benchmark)


@pytest.fixture
def connector_parts():
    storage = Storage()
    runner = Runner()
    client = AttachmentClient({"image": b"PNG bytes", "audio": b"MP3 bytes", "video": b"MP4 bytes"})
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=client,
        idempotency=InMemoryDiscordIdempotency(),
    )
    return connector, storage, runner, client


@pytest.mark.asyncio
async def test_text_message_maps_channel_thread_and_dispatches(connector_parts):
    connector, storage, runner, _ = connector_parts

    result = await connector.handle_message(
        {
            "id": "message-1",
            "channel": {"id": "channel-7"},
            "thread": {"id": "thread-9"},
            "content": "Please review this change",
            "author": {"id": "user-1", "username": "reviewer"},
        }
    )

    assert result.accepted is True
    assert result.benchmark is storage.benchmarks[0]
    assert result.benchmark.source == "discord"
    assert result.benchmark.conversation_id == "channel-7:thread-9"
    assert result.benchmark.prompt == "Please review this change"
    assert runner.benchmarks == [result.benchmark]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "filename", "expected_type", "payload"),
    [
        ("image/png", "image.png", InputType.IMAGE, b"PNG bytes"),
        ("audio/ogg", "voice.ogg", InputType.AUDIO, b"MP3 bytes"),
        ("video/webm", "clip.webm", InputType.VIDEO, b"MP4 bytes"),
    ],
)
async def test_supported_media_preserves_bytes_and_metadata(
    connector_parts, content_type, filename, expected_type, payload
):
    connector, _, _, client = connector_parts
    attachment_id = f"{expected_type.value}-1"
    client.files[attachment_id] = payload

    result = await connector.handle_message(
        {
            "id": f"message-{attachment_id}",
            "channel_id": "channel-7",
            "content": "Inspect this",
            "attachments": [
                {
                    "id": attachment_id,
                    "filename": filename,
                    "content_type": content_type,
                    "size": len(payload),
                    "url": f"https://cdn.example/{filename}",
                }
            ],
        }
    )

    assert result.accepted is True
    attachment = result.benchmark.attachments[0]
    assert attachment.type == expected_type
    assert attachment.filename == filename
    assert attachment.mime_type == content_type
    assert attachment.size_bytes == len(payload)
    assert attachment.content_bytes == payload
    assert attachment.url is None
    assert attachment.model_extra["discord_attachment_id"] == attachment_id
    assert attachment.model_extra["discord_source_url"] == f"https://cdn.example/{filename}"


@pytest.mark.asyncio
async def test_url_fallback_preserves_url_and_metadata(connector_parts):
    connector, _, _, client = connector_parts
    client.files["remote"] = None
    client.urls["remote"] = "https://cdn.example/remote.jpg"

    result = await connector.handle_message(
        {
            "id": "message-remote",
            "channel_id": "channel-7",
            "content": "Inspect image",
            "attachments": [
                {
                    "id": "remote",
                    "filename": "remote.jpg",
                    "content_type": "image/jpeg",
                    "size": 2048,
                }
            ],
        }
    )

    attachment = result.benchmark.attachments[0]
    assert attachment.url == "https://cdn.example/remote.jpg"
    assert attachment.content_bytes is None
    assert attachment.size_bytes == 2048
    assert attachment.model_extra["discord_attachment_id"] == "remote"


@pytest.mark.asyncio
async def test_attachment_only_message_gets_nonempty_prompt(connector_parts):
    connector, _, _, _ = connector_parts
    result = await connector.handle_message(
        {
            "id": "message-only-media",
            "channel_id": "channel-7",
            "attachments": [
                {
                    "id": "image",
                    "filename": "image.png",
                    "content_type": "image/png",
                }
            ],
        }
    )
    assert result.accepted is True
    assert result.benchmark.prompt == "[Discord attachment]"


@pytest.mark.asyncio
async def test_unsupported_attachment_is_structured_and_not_dispatched(connector_parts):
    connector, storage, runner, _ = connector_parts
    result = await connector.handle_message(
        {
            "id": "message-pdf",
            "channel_id": "channel-7",
            "attachments": [{"id": "pdf", "filename": "x.pdf", "content_type": "application/pdf"}],
        }
    )

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "unsupported_attachment"
    assert result.error.attachment_id == "pdf"
    assert result.error.modality == "application/pdf"
    assert storage.benchmarks == []
    assert runner.benchmarks == []


@pytest.mark.asyncio
async def test_missing_attachment_content_is_structured(connector_parts):
    connector, storage, runner, client = connector_parts
    client.files["missing"] = None
    result = await connector.handle_message(
        {
            "id": "message-missing",
            "channel_id": "channel-7",
            "attachments": [{"id": "missing", "filename": "clip.mp4", "content_type": "video/mp4"}],
        }
    )

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "attachment_content_unavailable"
    assert result.error.attachment_id == "missing"
    assert storage.benchmarks == []
    assert runner.benchmarks == []


@pytest.mark.asyncio
async def test_missing_content_and_attachments_is_rejected(connector_parts):
    connector, storage, runner, _ = connector_parts
    result = await connector.handle_message(
        {"id": "message-empty", "channel_id": "channel-7", "content": ""}
    )

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "empty_message"
    assert storage.benchmarks == []
    assert runner.benchmarks == []


@pytest.mark.asyncio
async def test_duplicate_event_or_message_id_dispatches_once(connector_parts):
    connector, storage, runner, _ = connector_parts
    message = {"id": "duplicate-1", "channel_id": "channel-7", "content": "same"}

    first = await connector.handle_message(message)
    second = await connector.handle_message(message)

    assert first.accepted is True
    assert second.accepted is False
    assert second.duplicate is True
    assert second.error is None
    assert len(storage.benchmarks) == 1
    assert len(runner.benchmarks) == 1


@pytest.mark.asyncio
async def test_event_envelope_id_is_used_for_atomic_claim(connector_parts):
    connector, _, runner, _ = connector_parts
    event = {
        "event_id": "event-1",
        "message": {"id": "message-1", "channel_id": "channel-7", "text": "hello"},
    }

    first = await connector.handle_message(event)
    second = await connector.handle_message(event)

    assert first.accepted is True
    assert second.duplicate is True
    assert len(runner.benchmarks) == 1


class ResponseClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[tuple[str, str]] = []
        self.error = error

    async def send_message(self, conversation_id: str, text: str) -> None:
        if self.error is not None:
            raise self.error
        self.messages.append((conversation_id, text))


class ResultStorage(Storage):
    def __init__(self, executions: list[Execution], lookup_error: Exception | None = None) -> None:
        super().__init__()
        self.executions = executions
        self.lookup_error = lookup_error

    async def get_executions(self, benchmark_id: str) -> list[Execution]:
        if self.lookup_error is not None:
            raise self.lookup_error
        return [
            execution.model_copy(update={"benchmark_id": benchmark_id})
            for execution in self.executions
        ]


def make_execution(
    agent_name: str,
    deployment: DeploymentType,
    response: str = "",
    errors: list[str] | None = None,
    success: bool = True,
) -> Execution:
    now = datetime.now(UTC)
    return Execution(
        benchmark_id="benchmark",
        agent_name=agent_name,
        agent_version="1.0",
        deployment=DeploymentMetrics(
            provider="test",
            deployment_type=deployment,
            total_latency_ms=1.0,
        ),
        result=ExecutionResult(raw_response=response, errors=errors or []),
        started_at=now,
        completed_at=now,
        success=success,
    )


@pytest.mark.asyncio
async def test_delivers_exact_responses_with_agent_deployment_and_version():
    storage = ResultStorage(
        [make_execution("hermes", DeploymentType.LOCAL_DOCKER, "Exact\nanswer")]
    )
    response_client = ResponseClient()
    connector = DiscordConnector(
        storage=storage,
        runner=Runner(),
        discord=AttachmentClient({}),
        response_client=response_client,
    )

    result = await connector.handle_message(
        {"id": "delivery-1", "channel_id": "channel-7", "content": "question"}
    )

    assert result.accepted is True
    assert result.delivered is True
    conversation_id, text = response_client.messages[0]
    assert conversation_id == "channel-7"
    assert "Agent: hermes" in text
    assert "Deployment: local_docker" in text
    assert "Version: 1.0" in text
    assert "Exact\nanswer" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("modality", [InputType.IMAGE, InputType.AUDIO, InputType.VIDEO])
async def test_delivers_failed_modality_errors_visibly(modality):
    error = f"unsupported_modality:{modality.value}"
    storage = ResultStorage(
        [
            make_execution("hermes", DeploymentType.LOCAL_DOCKER, "available"),
            make_execution(
                "openclaw",
                DeploymentType.VIRTUAL_MACHINE,
                errors=[error],
                success=False,
            ),
        ]
    )
    response_client = ResponseClient()
    connector = DiscordConnector(
        storage=storage,
        runner=Runner(),
        discord=AttachmentClient({}),
        response_client=response_client,
    )

    result = await connector.handle_message(
        {"id": f"modality-{modality.value}", "channel_id": "channel-7", "content": "question"}
    )

    assert result.accepted is True
    text = response_client.messages[0][1]
    assert "available" in text
    assert "Agent: openclaw" in text
    assert "Status: failed" in text
    assert error in text


@pytest.mark.asyncio
async def test_send_failure_is_token_safe_and_does_not_claim_success():
    storage = ResultStorage([make_execution("hermes", DeploymentType.LOCAL_DOCKER, "answer")])
    response_client = ResponseClient(RuntimeError("bot token=secret-token"))
    connector = DiscordConnector(
        storage=storage,
        runner=Runner(),
        discord=AttachmentClient({}),
        response_client=response_client,
    )

    result = await connector.handle_message(
        {"id": "send-failure", "channel_id": "channel-7", "content": "question"}
    )

    assert result.accepted is False
    assert result.delivered is False
    assert result.error is not None
    assert result.error.code == "delivery_failure"
    assert "secret-token" not in result.error.message
    assert storage.benchmarks


@pytest.mark.asyncio
async def test_execution_lookup_failure_is_token_safe_and_retains_benchmark():
    storage = ResultStorage([], lookup_error=RuntimeError("database token=secret-token"))
    connector = DiscordConnector(
        storage=storage,
        runner=Runner(),
        discord=AttachmentClient({}),
        response_client=ResponseClient(),
    )

    result = await connector.handle_message(
        {"id": "lookup-failure", "channel_id": "channel-7", "content": "question"}
    )

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "execution_lookup_failure"
    assert "secret-token" not in result.error.message
    assert storage.benchmarks


@pytest.mark.asyncio
async def test_duplicate_event_does_not_create_duplicate_response():
    storage = ResultStorage([make_execution("hermes", DeploymentType.LOCAL_DOCKER, "answer")])
    response_client = ResponseClient()
    connector = DiscordConnector(
        storage=storage,
        runner=Runner(),
        discord=AttachmentClient({}),
        response_client=response_client,
        idempotency=InMemoryDiscordIdempotency(),
    )
    message = {"id": "duplicate-delivery", "channel_id": "channel-7", "content": "same"}

    first = await connector.handle_message(message)
    second = await connector.handle_message(message)

    assert first.accepted is True
    assert first.delivered is True
    assert second.duplicate is True
    assert len(storage.benchmarks) == 1
    assert len(response_client.messages) == 1
