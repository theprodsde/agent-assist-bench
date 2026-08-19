"""SQLite integration coverage for Discord benchmark dispatch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from benchmark.connectors.discord import (
    DiscordAttachment,
    DiscordConnector,
    InMemoryDiscordIdempotency,
    InMemoryDiscordResponseIdempotency,
)
from benchmark.models.domain import (
    DeploymentMetrics,
    DeploymentType,
    Execution,
    ExecutionResult,
)
from benchmark.storage.manager import BenchmarkFilters, StorageManager

if TYPE_CHECKING:
    from benchmark.models.domain import Benchmark


# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------


class ByteClient:
    """Deterministic Discord attachment client with injectable failures."""

    def __init__(
        self,
        payload: bytes | None = b"discord-bytes",
        urls: dict[str, str] | None = None,
        download_error: Exception | None = None,
        url_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.urls = urls or {}
        self.download_error = download_error
        self.url_error = url_error

    async def download_bytes(self, attachment: DiscordAttachment) -> bytes | None:
        if self.download_error is not None:
            raise self.download_error
        return self.payload

    async def resolve_url(self, attachment: DiscordAttachment) -> str | None:
        if self.url_error is not None:
            raise self.url_error
        return self.urls.get(attachment.id)


class PersistingRunner:
    """Records dispatched benchmarks without persisting execution results."""

    def __init__(self) -> None:
        self.requests: list[Benchmark] = []

    async def run(self, benchmark: Benchmark) -> None:
        self.requests.append(benchmark)


class PersistedExecutionRunner:
    """Fake runner that records its request and persists a deterministic result."""

    def __init__(self, storage: StorageManager, error: str | None = None) -> None:
        self.storage = storage
        self.error = error
        self.requests: list[Benchmark] = []

    async def run(self, benchmark: Benchmark) -> None:
        self.requests.append(benchmark)
        now = datetime.now(UTC)
        await self.storage.save_execution(
            Execution(
                benchmark_id=benchmark.id,
                agent_name="discord-test-agent",
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


class RecordingResponseClient:
    """Records all messages delivered to Discord channels."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_message(self, conversation_id: str, text: str) -> None:
        self.messages.append((conversation_id, text))


class FailingRunner:
    """Runner that always raises a RuntimeError."""

    async def run(self, benchmark: Benchmark) -> None:
        raise RuntimeError("runner unavailable")


class FailingResponseClient:
    """Response client that raises on every delivery attempt."""

    async def send_message(self, conversation_id: str, text: str) -> None:
        raise RuntimeError("discord API token=secret")


class FailOnceStorage(StorageManager):
    """SQLite storage that fails the first save_benchmark call."""

    def __init__(self, db_path) -> None:
        super().__init__(db_path)
        self.fail_next_save = True

    async def save_benchmark(self, benchmark) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("sqlite write failed")
        await super().save_benchmark(benchmark)


# ---------------------------------------------------------------------------
# 1. Existing tests (persists full message, channel text, duplicate)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_connector_persists_and_dispatches_full_message(tmp_path):
    storage = StorageManager(tmp_path / "discord.db")
    await storage.initialize()
    runner = PersistingRunner()
    connector = DiscordConnector(storage=storage, runner=runner, discord=ByteClient())

    result = await connector.handle_message(
        {
            "id": "discord-message-1",
            "channel": {"id": "channel-42"},
            "thread": {"id": "thread-9", "parent_id": "channel-42"},
            "content": "Keep all attachment data",
            "attachments": [
                {
                    "id": "image-1",
                    "filename": "evidence.png",
                    "content_type": "image/png",
                    "size": 15,
                    "url": "https://cdn.example/evidence.png",
                }
            ],
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    assert saved.source == "discord"
    assert saved.conversation_id == "channel-42:thread-9"
    assert saved.prompt == "Keep all attachment data"
    assert saved.attachments[0].filename == "evidence.png"
    assert saved.attachments[0].mime_type == "image/png"
    assert saved.attachments[0].size_bytes == 15
    assert saved.attachments[0].content_bytes == b"discord-bytes"
    assert saved.attachments[0].model_extra["discord_attachment_id"] == "image-1"
    assert runner.requests == [result.benchmark]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_channel_text_reaches_runner_and_round_trips(tmp_path):
    storage = StorageManager(tmp_path / "discord-text.db")
    await storage.initialize()
    runner = PersistingRunner()
    connector = DiscordConnector(storage=storage, runner=runner, discord=ByteClient())

    result = await connector.handle_message(
        {
            "id": "discord-message-2",
            "channel_id": "channel-7",
            "text": "exact Discord text prompt",
        }
    )
    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    assert saved.prompt == "exact Discord text prompt"
    assert saved.source == "discord"
    assert saved.conversation_id == "channel-7"
    assert runner.requests == [result.benchmark]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_duplicate_event_does_not_create_second_record(tmp_path):
    storage = StorageManager(tmp_path / "discord-duplicate.db")
    await storage.initialize()
    runner = PersistingRunner()
    connector = DiscordConnector(storage=storage, runner=runner, discord=ByteClient())
    message = {"id": "discord-duplicate", "channel_id": "channel-7", "content": "same"}

    first = await connector.handle_message(message)
    second = await connector.handle_message(message)
    benchmarks = await storage.list_benchmarks(BenchmarkFilters())
    await storage.close()

    assert first.accepted is True
    assert second.duplicate is True
    assert len(benchmarks) == 1
    assert len(runner.requests) == 1


# ---------------------------------------------------------------------------
# 2. Media round-trip tests (parametrized for image, audio, video)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "filename", "expected_type"),
    [
        ("image/png", "photo.png", "image"),
        ("audio/ogg", "voice.ogg", "audio"),
        ("video/webm", "clip.webm", "video"),
    ],
)
async def test_discord_media_round_trips_metadata_bytes_and_runner_request(
    tmp_path, content_type, filename, expected_type
):
    storage = StorageManager(tmp_path / f"{expected_type}.db")
    await storage.initialize()
    payload = f"exact-{expected_type}-bytes".encode()
    client = ByteClient(payload=payload)
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=client,
        idempotency=InMemoryDiscordIdempotency(),
    )

    message = {
        "id": f"media-{expected_type}",
        "channel": {"id": "channel-42"},
        "thread": {"id": "thread-7", "parent_id": "channel-42"},
        "content": "inspect",
        "attachments": [
            {
                "id": f"{expected_type}-att-1",
                "filename": filename,
                "content_type": content_type,
                "size": len(payload),
                "url": f"https://cdn.example/{filename}",
            }
        ],
    }
    result = await connector.handle_message(message)

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert result.benchmark.source == "discord"
    assert result.benchmark.conversation_id == "channel-42:thread-7"
    # Runner received the same attachment as the persisted benchmark
    assert (
        runner.requests[0].attachments[0].model_dump()
        == result.benchmark.attachments[0].model_dump()
    )
    assert saved is not None
    attachment = saved.attachments[0]
    assert attachment.type.value == expected_type
    assert attachment.filename == filename
    assert attachment.mime_type == content_type
    assert attachment.size_bytes == len(payload)
    assert attachment.content_bytes == payload
    assert attachment.url is None
    assert attachment.model_extra["discord_attachment_id"] == f"{expected_type}-att-1"


# ---------------------------------------------------------------------------
# 3. Text-only message maps channel/thread and reaches runner
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_text_maps_channel_thread_and_reaches_runner(tmp_path):
    storage = StorageManager(tmp_path / "text.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=ByteClient(),
        idempotency=InMemoryDiscordIdempotency(),
    )

    result = await connector.handle_message(
        {
            "id": "text-1",
            "channel": {"id": "chat-9"},
            "thread": {"id": "thread-2", "parent_id": "chat-9"},
            "content": "exact text prompt",
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    assert saved.source == "discord"
    assert saved.conversation_id == "chat-9:thread-2"
    assert saved.prompt == "exact text prompt"
    assert runner.requests == [result.benchmark]


# ---------------------------------------------------------------------------
# 4. URL fallback test (download_bytes returns None, URL available)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_url_round_trips_when_bytes_unavailable(tmp_path):
    storage = StorageManager(tmp_path / "url.db")
    await storage.initialize()
    # download_bytes returns None; source URL in the attachment itself
    client = ByteClient(payload=None)
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=client,
        idempotency=InMemoryDiscordIdempotency(),
    )

    source_url = "https://cdn.discord.example/files/original.jpg"
    result = await connector.handle_message(
        {
            "id": "url-1",
            "channel_id": "channel-42",
            "content": "inspect remote image",
            "attachments": [
                {
                    "id": "remote-image",
                    "filename": "original.jpg",
                    "content_type": "image/jpeg",
                    "size": 4096,
                    "url": source_url,
                }
            ],
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    attachment = saved.attachments[0]
    assert attachment.url == source_url
    assert attachment.content_bytes is None
    assert attachment.filename == "original.jpg"
    assert attachment.mime_type == "image/jpeg"
    assert attachment.size_bytes == 4096
    assert attachment.model_extra["discord_source_url"] == source_url


# ---------------------------------------------------------------------------
# 5. URL fallback via resolve_url (no source URL in attachment, resolved)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_url_fallback_via_resolve_url(tmp_path):
    storage = StorageManager(tmp_path / "url-resolve.db")
    await storage.initialize()
    resolved_url = "https://cdn.discord.example/resolved/voice.ogg"
    client = ByteClient(payload=None, urls={"audio-resolve": resolved_url})
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=client,
        idempotency=InMemoryDiscordIdempotency(),
    )

    result = await connector.handle_message(
        {
            "id": "url-resolve-1",
            "channel_id": "channel-42",
            "content": "resolve fallback",
            "attachments": [
                {
                    "id": "audio-resolve",
                    "filename": "voice.ogg",
                    "content_type": "audio/ogg",
                    "size": 2048,
                    # No url/proxy_url on attachment
                }
            ],
        }
    )

    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert saved is not None
    attachment = saved.attachments[0]
    assert attachment.url == resolved_url
    assert attachment.content_bytes is None
    assert attachment.filename == "voice.ogg"
    assert attachment.mime_type == "audio/ogg"
    assert attachment.size_bytes == 2048


# ---------------------------------------------------------------------------
# 6. Response delivery from SQLite
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_delivers_exact_response_and_persisted_error(tmp_path):
    storage = StorageManager(tmp_path / "delivery.db")
    await storage.initialize()
    response_client = RecordingResponseClient()
    runner = PersistedExecutionRunner(storage, error="unsupported_modality:image")
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=ByteClient(),
        idempotency=InMemoryDiscordIdempotency(),
        response_client=response_client,
    )

    result = await connector.handle_message(
        {"id": "delivery-1", "channel_id": "channel-42", "content": "run"}
    )
    executions = await storage.get_executions(result.benchmark.id)
    await storage.close()

    assert result.accepted is True
    assert result.delivered is True
    assert len(executions) == 1
    assert executions[0].result.raw_response == "exact persisted agent response"
    assert executions[0].result.errors == ["unsupported_modality:image"]
    conversation_id, delivered = response_client.messages[0]
    assert conversation_id == "channel-42"
    assert "exact persisted agent response" in delivered
    assert "unsupported_modality:image" in delivered
    assert "Status: failed" in delivered


# ---------------------------------------------------------------------------
# 7. Failure handling tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_api_failure_is_structured_and_not_persisted(tmp_path):
    """Attachment API failure produces structured error, no benchmark persisted."""
    storage = StorageManager(tmp_path / "api-failure.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=ByteClient(
            payload=None,
            download_error=RuntimeError("token=secret"),
            url_error=RuntimeError("token=secret"),
        ),
        idempotency=InMemoryDiscordIdempotency(),
    )

    result = await connector.handle_message(
        {
            "id": "api-failure-1",
            "channel_id": "channel-42",
            "content": "trigger failure",
            "attachments": [
                {
                    "id": "broken",
                    "filename": "broken.mp3",
                    "content_type": "audio/mpeg",
                    "size": 100,
                }
            ],
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
async def test_discord_dispatch_failure_leaves_one_persisted_benchmark(tmp_path):
    """Runner failure leaves benchmark persisted, error structured."""
    storage = StorageManager(tmp_path / "dispatch-failure.db")
    await storage.initialize()
    connector = DiscordConnector(
        storage=storage,
        runner=FailingRunner(),
        discord=ByteClient(),
        idempotency=InMemoryDiscordIdempotency(),
    )

    result = await connector.handle_message(
        {"id": "dispatch-failure-1", "channel_id": "channel-42", "content": "run"}
    )
    saved = await storage.get_benchmark(result.benchmark.id)
    await storage.close()

    assert result.accepted is False
    assert result.error is not None
    assert result.error.code == "dispatch_failure"
    assert saved is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_storage_failure_is_structured_without_partial_record(tmp_path):
    """Storage failure produces structured error, no partial record, no runner call."""
    storage = FailOnceStorage(tmp_path / "storage-failure.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=ByteClient(),
        idempotency=InMemoryDiscordIdempotency(),
    )

    result = await connector.handle_message(
        {"id": "storage-failure-1", "channel_id": "channel-42", "content": "run"}
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
async def test_discord_response_api_failure_keeps_persisted_execution(tmp_path):
    """Response delivery API failure: execution persisted, error structured, token-safe."""
    storage = StorageManager(tmp_path / "response-failure.db")
    await storage.initialize()
    runner = PersistedExecutionRunner(storage)
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=ByteClient(),
        idempotency=InMemoryDiscordIdempotency(),
        response_client=FailingResponseClient(),
    )

    result = await connector.handle_message(
        {"id": "response-failure-1", "channel_id": "channel-42", "content": "run"}
    )
    executions = await storage.get_executions(result.benchmark.id)
    await storage.close()

    assert result.accepted is False
    assert result.delivered is False
    assert result.error is not None
    assert result.error.code == "delivery_failure"
    assert "secret" not in result.error.message
    assert len(executions) == 1
    assert executions[0].result.raw_response == "exact persisted agent response"


# ---------------------------------------------------------------------------
# 8. Duplicate handling (event + response delivery suppression)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_duplicate_event_and_response_are_delivered_once(tmp_path):
    """Duplicate event/message AND duplicate response delivery suppression."""
    storage = StorageManager(tmp_path / "duplicates.db")
    await storage.initialize()
    response_client = RecordingResponseClient()
    runner = PersistedExecutionRunner(storage)
    idempotency = InMemoryDiscordIdempotency()
    response_idempotency = InMemoryDiscordResponseIdempotency()
    connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=ByteClient(),
        idempotency=idempotency,
        response_client=response_client,
        response_idempotency=response_idempotency,
    )
    message = {"id": "duplicate-1", "channel_id": "channel-42", "content": "same"}

    first = await connector.handle_message(message)
    second = await connector.handle_message(message)
    # Attempt duplicate delivery via internal method
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
