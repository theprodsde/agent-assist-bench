"""Unit tests for the framework-neutral Telegram connector boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from benchmark.connectors.telegram import (
    InMemoryTelegramIdempotency,
    TelegramConnector,
    TelegramFile,
)
from benchmark.models.domain import (
    DeploymentMetrics,
    DeploymentType,
    Execution,
    ExecutionResult,
    InputType,
)


class FileClient:
    """SDK-free Telegram API test double."""

    def __init__(self, files: dict[str, bytes | None], urls: dict[str, str] | None = None):
        self.files = files
        self.urls = urls or {}
        self.get_file = AsyncMock(return_value=None)

    async def download_file(self, file_id: str) -> bytes | None:
        return self.files.get(file_id)

    async def resolve_file_url(self, file_id: str) -> str | None:
        return self.urls.get(file_id)


class Runner:
    def __init__(self) -> None:
        self.benchmarks = []

    async def run(self, benchmark):
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
    client = FileClient(
        {
            "photo": b"PNG bytes",
            "audio": b"MP3 bytes",
            "video": b"MP4 bytes",
        }
    )
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=client,
        idempotency=InMemoryTelegramIdempotency(),
    )
    return connector, storage, runner, client


@pytest.mark.asyncio
async def test_text_update_maps_chat_and_dispatches(connector_parts):
    connector, storage, runner, _ = connector_parts

    result = await connector.handle_update(
        {
            "update_id": 101,
            "message": {
                "message_id": 4,
                "chat": {"id": 77},
                "message_thread_id": 9,
                "text": "Please review this change",
            },
        }
    )

    assert result.accepted is True
    assert result.benchmark is storage.benchmarks[0]
    assert result.benchmark.source == "telegram"
    assert result.benchmark.conversation_id == "77:9"
    assert result.benchmark.prompt == "Please review this change"
    assert runner.benchmarks == [result.benchmark]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "file_id", "expected_type", "mime", "filename"),
    [
        ("photo", "photo", InputType.IMAGE, "image/jpeg", "photo"),
        ("audio", "audio", InputType.AUDIO, "audio/mpeg", "voice.mp3"),
        ("video", "video", InputType.VIDEO, "video/mp4", "clip.mp4"),
    ],
)
async def test_supported_media_preserves_bytes_and_metadata(
    connector_parts, field, file_id, expected_type, mime, filename
):
    connector, _, _, client = connector_parts
    media = {"file_id": file_id, "file_unique_id": f"unique-{file_id}", "file_size": 999}
    if field == "photo":
        media.update({"width": 100, "height": 100})
        message = {"photo": [media]}
    else:
        media.update({"mime_type": mime, "file_name": filename})
        message = {field: media}
    client.files[file_id] = b"actual bytes"

    result = await connector.handle_update(
        {"update_id": file_id, "message": {"chat_id": 77, **message}}
    )

    assert result.accepted is True
    attachment = result.benchmark.attachments[0]
    assert attachment.type == expected_type
    assert attachment.content_bytes == b"actual bytes"
    assert attachment.size_bytes == len(b"actual bytes")
    assert attachment.mime_type == mime
    assert attachment.model_extra["connector_file_id"] == file_id
    assert attachment.model_extra["telegram_file_unique_id"] == f"unique-{file_id}"
    assert attachment.filename == filename


@pytest.mark.asyncio
async def test_url_fallback_preserves_file_metadata(connector_parts):
    connector, _, _, client = connector_parts
    client.files["remote"] = None
    client.urls["remote"] = "https://api.example/files/remote"
    client.get_file.return_value = TelegramFile(
        file_id="remote",
        file_path="photos/original.png",
        file_size=2048,
        mime_type="image/png",
    )

    result = await connector.handle_update(
        {
            "update_id": 102,
            "message": {
                "chat": {"id": "chat-a"},
                "caption": "Inspect image",
                "photo": [{"file_id": "remote", "file_size": 10}],
            },
        }
    )

    attachment = result.benchmark.attachments[0]
    assert attachment.url == "https://api.example/files/remote"
    assert attachment.content_bytes is None
    assert attachment.filename == "original.png"
    assert attachment.mime_type == "image/png"
    assert attachment.size_bytes == 10
    assert attachment.model_extra["telegram_file_path"] == "photos/original.png"


@pytest.mark.asyncio
async def test_missing_content_is_structured_and_not_dispatched(connector_parts):
    connector, storage, runner, _ = connector_parts

    result = await connector.handle_update(
        {"update_id": 103, "message": {"chat_id": 77, "audio": {"file_id": "missing"}}}
    )

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "attachment_content_unavailable"
    assert result.error.file_id == "missing"
    assert storage.benchmarks == []
    assert runner.benchmarks == []


@pytest.mark.asyncio
async def test_unsupported_document_is_explicit(connector_parts):
    connector, storage, runner, _ = connector_parts

    result = await connector.handle_update(
        {
            "update_id": 104,
            "message": {
                "chat_id": 77,
                "document": {"file_id": "document", "file_name": "x.pdf"},
            },
        }
    )

    assert result.accepted is False
    assert result.error.code == "unsupported_attachment"
    assert result.error.modality == "document"
    assert storage.benchmarks == []
    assert runner.benchmarks == []


@pytest.mark.asyncio
async def test_duplicate_update_never_creates_second_benchmark(connector_parts):
    connector, storage, runner, _ = connector_parts
    update = {"update_id": 105, "message": {"chat_id": 77, "text": "same"}}

    first = await connector.handle_update(update)
    second = await connector.handle_update(update)

    assert first.accepted is True
    assert second.accepted is False
    assert second.duplicate is True
    assert second.error is None
    assert len(storage.benchmarks) == 1
    assert len(runner.benchmarks) == 1


class ResultStorage(Storage):
    def __init__(self, executions):
        super().__init__()
        self.executions = executions

    async def get_executions(self, benchmark_id: str):
        return self.executions


class ResponseClient:
    def __init__(self, failure: Exception | None = None) -> None:
        self.messages: list[tuple[str, str]] = []
        self.failure = failure

    async def send_message(self, conversation_id: str, text: str) -> None:
        if self.failure is not None:
            raise self.failure
        self.messages.append((conversation_id, text))


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
async def test_delivers_actual_response_with_agent_and_deployment_identity():
    storage = ResultStorage([make_execution("hermes", DeploymentType.LOCAL_DOCKER, "Exact answer")])
    response_client = ResponseClient()
    connector = TelegramConnector(
        storage=storage,
        runner=Runner(),
        telegram=FileClient({}),
        response_client=response_client,
    )

    result = await connector.handle_update(
        {"update_id": 201, "message": {"chat_id": 77, "text": "question"}}
    )

    assert result.accepted is True
    assert result.delivered is True
    assert response_client.messages[0][0] == "77"
    message = response_client.messages[0][1]
    assert "Agent: hermes" in message
    assert "Deployment: local_docker" in message
    assert "Exact answer" in message


@pytest.mark.asyncio
async def test_delivers_mixed_response_and_explicit_modality_error():
    storage = ResultStorage(
        [
            make_execution("hermes", DeploymentType.LOCAL_DOCKER, "Available response"),
            make_execution(
                "openclaw",
                DeploymentType.VIRTUAL_MACHINE,
                errors=["unsupported_modality:image"],
                success=False,
            ),
        ]
    )
    response_client = ResponseClient()
    connector = TelegramConnector(
        storage=storage,
        runner=Runner(),
        telegram=FileClient({}),
        response_client=response_client,
    )

    result = await connector.handle_update(
        {"update_id": 202, "message": {"chat_id": 77, "text": "question"}}
    )

    assert result.delivered is True
    message = response_client.messages[0][1]
    assert "Available response" in message
    assert "Agent: openclaw" in message
    assert "Deployment: vm" in message
    assert "Status: failed" in message
    assert "unsupported_modality:image" in message


@pytest.mark.asyncio
async def test_send_failure_is_token_safe_and_does_not_claim_success():
    storage = ResultStorage([make_execution("hermes", DeploymentType.LOCAL_DOCKER, "answer")])
    response_client = ResponseClient(RuntimeError("bot token=secret-token"))
    connector = TelegramConnector(
        storage=storage,
        runner=Runner(),
        telegram=FileClient({}),
        response_client=response_client,
    )

    result = await connector.handle_update(
        {"update_id": 203, "message": {"chat_id": 77, "text": "question"}}
    )

    assert result.accepted is False
    assert result.delivered is False
    assert result.error is not None
    assert result.error.code == "delivery_failure"
    assert "secret-token" not in result.error.message


@pytest.mark.asyncio
async def test_duplicate_update_delivers_once():
    storage = ResultStorage([make_execution("hermes", DeploymentType.LOCAL_DOCKER, "answer")])
    response_client = ResponseClient()
    connector = TelegramConnector(
        storage=storage,
        runner=Runner(),
        telegram=FileClient({}),
        response_client=response_client,
    )
    update = {"update_id": 204, "message": {"chat_id": 77, "text": "question"}}

    first = await connector.handle_update(update)
    second = await connector.handle_update(update)

    assert first.delivered is True
    assert second.duplicate is True
    assert len(response_client.messages) == 1
