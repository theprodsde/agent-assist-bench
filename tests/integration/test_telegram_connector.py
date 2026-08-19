"""SQLite boundary coverage for Telegram benchmark dispatch."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benchmark.connectors.telegram import InMemoryTelegramIdempotency, TelegramConnector
from benchmark.models.domain import (
    DeploymentMetrics,
    DeploymentType,
    Execution,
    ExecutionResult,
)
from benchmark.storage.manager import BenchmarkFilters, StorageManager


class ByteClient:
    async def download_file(self, file_id: str) -> bytes | None:
        return b"\x00telegram\xff"

    async def resolve_file_url(self, file_id: str) -> str | None:
        return None


class RecordingRunner:
    def __init__(self) -> None:
        self.benchmarks = []

    async def run(self, benchmark) -> None:
        self.benchmarks.append(benchmark)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_connector_persists_and_dispatches_full_attachment(tmp_path):
    storage = StorageManager(tmp_path / "telegram.db")
    await storage.initialize()
    runner = RecordingRunner()
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=ByteClient(),
        idempotency=InMemoryTelegramIdempotency(),
    )

    result = await connector.handle_update(
        {
            "update_id": 501,
            "message": {
                "chat": {"id": 42},
                "text": "Keep all image data",
                "photo": [
                    {"file_id": "small", "width": 10, "height": 10},
                    {"file_id": "large", "width": 100, "height": 100},
                ],
            },
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    assert saved.source == "telegram"
    assert saved.conversation_id == "42"
    assert saved.attachments[0].content_bytes == b"\x00telegram\xff"
    assert saved.attachments[0].model_extra["connector_file_id"] == "large"
    assert runner.benchmarks == [result.benchmark]


class PersistingRunner:
    def __init__(self, storage: StorageManager) -> None:
        self.storage = storage

    async def run(self, benchmark) -> None:
        now = datetime.now(UTC)
        await self.storage.save_execution(
            Execution(
                benchmark_id=benchmark.id,
                agent_name="hermes",
                agent_version="test",
                deployment=DeploymentMetrics(
                    provider="test",
                    deployment_type=DeploymentType.LOCAL_DOCKER,
                    total_latency_ms=1.0,
                ),
                result=ExecutionResult(raw_response="SQLite-backed Telegram answer"),
                started_at=now,
                completed_at=now,
                success=True,
            )
        )


class RecordingResponseClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_message(self, conversation_id: str, text: str) -> None:
        self.messages.append((conversation_id, text))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_connector_delivers_results_from_sqlite(tmp_path):
    storage = StorageManager(tmp_path / "telegram-response.db")
    await storage.initialize()
    response_client = RecordingResponseClient()
    connector = TelegramConnector(
        storage=storage,
        runner=PersistingRunner(storage),
        telegram=ByteClient(),
        idempotency=InMemoryTelegramIdempotency(),
        response_client=response_client,
    )

    result = await connector.handle_update(
        {"update_id": 502, "message": {"chat": {"id": 42}, "text": "Answer me"}}
    )

    executions = await storage.get_executions(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert result.delivered is True
    assert len(executions) == 1
    assert response_client.messages[0][0] == "42"
    assert "SQLite-backed Telegram answer" in response_client.messages[0][1]
    assert "Agent: hermes" in response_client.messages[0][1]


class MetadataFileClient:
    """Deterministic Telegram file API fake with injectable failures."""

    def __init__(
        self,
        files: dict[str, bytes | None],
        urls: dict[str, str] | None = None,
        metadata: dict[str, dict[str, object]] | None = None,
        download_error: Exception | None = None,
        url_error: Exception | None = None,
    ) -> None:
        self.files = files
        self.urls = urls or {}
        self.metadata = metadata or {}
        self.download_error = download_error
        self.url_error = url_error

    async def download_file(self, file_id: str) -> bytes | None:
        if self.download_error is not None:
            raise self.download_error
        return self.files.get(file_id)

    async def resolve_file_url(self, file_id: str) -> str | None:
        if self.url_error is not None:
            raise self.url_error
        return self.urls.get(file_id)

    async def get_file(self, file_id: str) -> dict[str, object] | None:
        return self.metadata.get(file_id)


class PersistedExecutionRunner:
    """Fake runner that records its request and persists a deterministic result."""

    def __init__(self, storage: StorageManager, error: str | None = None) -> None:
        self.storage = storage
        self.error = error
        self.requests = []

    async def run(self, benchmark) -> None:
        self.requests.append(benchmark)
        now = datetime.now(UTC)
        await self.storage.save_execution(
            Execution(
                benchmark_id=benchmark.id,
                agent_name="telegram-test-agent",
                agent_version="test",
                deployment=DeploymentMetrics(
                    provider="test",
                    deployment_type=DeploymentType.LOCAL_DOCKER,
                    total_latency_ms=1.0,
                ),
                result=ExecutionResult(
                    raw_response="exact persisted agent response",
                    errors=[self.error] if self.error else [],
                ),
                started_at=now,
                completed_at=now,
                success=self.error is None,
            )
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "file_id", "mime_type", "filename", "expected_type"),
    [
        ("photo", "image-1", "image/png", "photo.png", "image"),
        ("audio", "audio-1", "audio/ogg", "voice.ogg", "audio"),
        ("video", "video-1", "video/webm", "clip.webm", "video"),
    ],
)
async def test_telegram_media_round_trips_metadata_bytes_and_runner_request(
    tmp_path, field, file_id, mime_type, filename, expected_type
):
    storage = StorageManager(tmp_path / f"{expected_type}.db")
    await storage.initialize()
    payload = f"exact-{expected_type}-bytes".encode()
    client = MetadataFileClient(
        {file_id: payload},
        metadata={
            file_id: {
                "file_id": file_id,
                "file_unique_id": f"unique-{file_id}",
                "file_size": len(payload),
                "file_path": f"telegram/{filename}",
                "mime_type": mime_type,
            }
        },
    )
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(storage=storage, runner=runner, telegram=client)

    media = {
        "file_id": file_id,
        "file_unique_id": f"unique-{file_id}",
        "file_name": filename,
        "mime_type": mime_type,
        "file_size": len(payload),
    }
    message = {
        "chat": {"id": 42},
        "message_thread_id": 7,
        "text": "inspect",
        field: [media] if field == "photo" else media,
    }
    result = await connector.handle_update(
        {"update_id": f"media-{expected_type}", "message": message}
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert result.benchmark.source == "telegram"
    assert result.benchmark.conversation_id == "42:7"
    assert (
        runner.requests[0].attachments[0].model_dump()
        == result.benchmark.attachments[0].model_dump()
    )
    assert saved is not None
    attachment = saved.attachments[0]
    assert attachment.type.value == expected_type
    assert attachment.filename == filename
    assert attachment.mime_type == mime_type
    assert attachment.size_bytes == len(payload)
    assert attachment.content_bytes == payload
    assert attachment.url is None
    assert attachment.model_extra["connector_file_id"] == file_id
    assert attachment.model_extra["telegram_file_unique_id"] == f"unique-{file_id}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_text_maps_chat_thread_and_reaches_runner(tmp_path):
    storage = StorageManager(tmp_path / "text.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=MetadataFileClient({}),
    )

    result = await connector.handle_update(
        {
            "update_id": "text-1",
            "message": {
                "chat": {"id": "chat-9"},
                "message_thread_id": "thread-2",
                "text": "exact text prompt",
            },
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    assert saved.source == "telegram"
    assert saved.conversation_id == "chat-9:thread-2"
    assert saved.prompt == "exact text prompt"
    assert runner.requests == [result.benchmark]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_url_round_trips_url_and_resolved_metadata(tmp_path):
    storage = StorageManager(tmp_path / "url.db")
    await storage.initialize()
    file_id = "remote-image"
    url = "https://telegram.example/file/remote-image"
    client = MetadataFileClient(
        {file_id: None},
        urls={file_id: url},
        metadata={
            file_id: {
                "file_id": file_id,
                "file_unique_id": "remote-unique",
                "file_size": 4096,
                "file_path": "photos/original.jpg",
                "mime_type": "image/jpeg",
            }
        },
    )
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(storage=storage, runner=runner, telegram=client)

    result = await connector.handle_update(
        {
            "update_id": "url-1",
            "message": {
                "chat_id": 42,
                "caption": "inspect remote image",
                "photo": [{"file_id": file_id, "file_size": 4096}],
            },
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    attachment = saved.attachments[0]
    assert attachment.url == url
    assert attachment.content_bytes is None
    assert attachment.filename == "original.jpg"
    assert attachment.mime_type == "image/jpeg"
    assert attachment.size_bytes == 4096
    assert attachment.model_extra["telegram_file_path"] == "photos/original.jpg"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_delivers_exact_response_and_persisted_error(tmp_path):
    storage = StorageManager(tmp_path / "delivery.db")
    await storage.initialize()
    response_client = RecordingResponseClient()
    runner = PersistedExecutionRunner(storage, error="unsupported_modality:image")
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=MetadataFileClient({}),
        response_client=response_client,
    )

    result = await connector.handle_update(
        {"update_id": "delivery-1", "message": {"chat_id": 42, "text": "run"}}
    )
    executions = await storage.get_executions(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert result.delivered is True
    assert len(executions) == 1
    assert executions[0].result.raw_response == "exact persisted agent response"
    assert executions[0].result.errors == ["unsupported_modality:image"]
    conversation_id, delivered = response_client.messages[0]
    assert conversation_id == "42"
    assert "exact persisted agent response" in delivered
    assert "unsupported_modality:image" in delivered
    assert "Status: failed" in delivered


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_api_failure_is_structured_and_not_persisted(tmp_path):
    storage = StorageManager(tmp_path / "api-failure.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=MetadataFileClient(
            {"broken": None},
            download_error=RuntimeError("token=secret"),
            url_error=RuntimeError("token=secret"),
        ),
    )

    result = await connector.handle_update(
        {
            "update_id": "api-failure-1",
            "message": {"chat_id": 42, "audio": {"file_id": "broken"}},
        }
    )

    benchmarks = await storage.list_benchmarks(BenchmarkFilters())
    await storage.close()

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "attachment_content_unavailable"
    assert "secret" not in result.error.message
    assert benchmarks == []
    assert runner.requests == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_dispatch_failure_leaves_one_persisted_benchmark(tmp_path):
    storage = StorageManager(tmp_path / "dispatch-failure.db")
    await storage.initialize()

    class FailingRunner:
        async def run(self, benchmark) -> None:
            raise RuntimeError("runner unavailable")

    connector = TelegramConnector(
        storage=storage,
        runner=FailingRunner(),
        telegram=MetadataFileClient({}),
    )
    result = await connector.handle_update(
        {"update_id": "dispatch-failure-1", "message": {"chat_id": 42, "text": "run"}}
    )
    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "dispatch_failure"
    assert saved is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_duplicate_update_and_response_are_delivered_once(tmp_path):
    storage = StorageManager(tmp_path / "duplicates.db")
    await storage.initialize()
    response_client = RecordingResponseClient()
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=MetadataFileClient({}),
        response_client=response_client,
    )
    update = {"update_id": "duplicate-1", "message": {"chat_id": 42, "text": "same"}}

    first = await connector.handle_update(update)
    second = await connector.handle_update(update)
    duplicate_delivery, delivery_error = await connector._deliver_results(
        first.benchmark, "duplicate-1"
    )
    executions = await storage.get_executions(first.benchmark.id)
    await storage.close()

    assert first.accepted is True
    assert first.delivered is True
    assert second.duplicate is True
    assert duplicate_delivery is False
    assert delivery_error is None
    assert len(runner.requests) == 1
    assert len(executions) == 1
    assert len(response_client.messages) == 1


class FailOnceStorage(StorageManager):
    """SQLite storage fake that exposes connector persistence failure handling."""

    def __init__(self, db_path) -> None:
        super().__init__(db_path)
        self.fail_next_save = True

    async def save_benchmark(self, benchmark) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("sqlite write failed")
        await super().save_benchmark(benchmark)


class FailingResponseClient:
    async def send_message(self, conversation_id: str, text: str) -> None:
        raise RuntimeError("telegram API token=secret")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_storage_failure_is_structured_without_partial_record(tmp_path):
    storage = FailOnceStorage(tmp_path / "storage-failure.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=MetadataFileClient({}),
    )

    result = await connector.handle_update(
        {"update_id": "storage-failure-1", "message": {"chat_id": 42, "text": "run"}}
    )
    benchmarks = await storage.list_benchmarks(BenchmarkFilters())
    await storage.close()

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "storage_failure"
    assert benchmarks == []
    assert runner.requests == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_response_api_failure_keeps_persisted_execution(tmp_path):
    storage = StorageManager(tmp_path / "response-failure.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=MetadataFileClient({}),
        response_client=FailingResponseClient(),
    )

    result = await connector.handle_update(
        {"update_id": "response-failure-1", "message": {"chat_id": 42, "text": "run"}}
    )
    executions = await storage.get_executions(result.benchmark.id)
    await storage.close()

    assert result.accepted is False
    assert result.delivered is False
    assert result.error is not None
    assert result.error.code == "delivery_failure"
    assert len(executions) == 1
    assert executions[0].result.raw_response == "exact persisted agent response"
