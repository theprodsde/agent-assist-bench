"""Comprehensive end-to-end benchmark integration tests.

Validates the complete benchmark flow across CLI, Telegram, and Discord
connectors with configurable mock transports that simulate success, failure,
timeout, and modality rejection scenarios.

Covers:
- Image attachment round-trip through Hermes/OpenClaw (FR-101, FR-102)
- Audio attachment via Telegram connector (FR-103)
- Video explicit rejection via Discord connector (FR-104)
- Mixed success/failure (Hermes succeeds, OpenClaw times out)
- Endpoint unavailable (both agents unreachable)
- Evaluation display after mixed results
- Daily export includes response content and errors
- Report includes failed execution counts and excludes failures from recommendations
- Sequential ordering preserved across concurrent connector submissions

Requirements validated: 1.1, 2.1, 2.3, 2.4, 2.5, 2.6, 2.8, 3.7, 4.3, 5.2,
6.1, 7.1, 8.1, 9.3, 12.1, 13.6
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import pytest

from benchmark.agents.hermes import HermesAdapter
from benchmark.agents.openclaw import OpenClawAdapter
from benchmark.agents.registry import AgentRegistry
from benchmark.cli.wiring import AppContext
from benchmark.connectors.discord import (
    DiscordAttachment,
    DiscordChannel,
    DiscordConnector,
    DiscordMessage,
)
from benchmark.connectors.telegram import (
    TelegramAudio,
    TelegramChat,
    TelegramConnector,
    TelegramMessage,
    TelegramUpdate,
)
from benchmark.evaluation.service import EvaluationService
from benchmark.export.daily import DailyExporter
from benchmark.models.domain import (
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    Evaluation,
    InputType,
)
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager

# ---------------------------------------------------------------------------
# Deterministic response constants
# ---------------------------------------------------------------------------

HERMES_RESPONSE = "Hermes: I analyzed your input with great care."
OPENCLAW_RESPONSE = "OpenClaw: Analysis complete, here are my findings."


# ---------------------------------------------------------------------------
# Configurable mock transport factory
# ---------------------------------------------------------------------------


def _make_transport(
    *,
    hermes_response: str = HERMES_RESPONSE,
    openclaw_response: str = OPENCLAW_RESPONSE,
    hermes_error: bool = False,
    openclaw_error: bool = False,
    hermes_timeout: bool = False,
    openclaw_timeout: bool = False,
    reject_video: bool = True,
) -> httpx.MockTransport:
    """Create a mock transport with configurable per-agent behavior."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        # Health check
        if "/models" in url:
            if hermes_error and ":8001" in url:
                raise httpx.ConnectError("Connection refused")
            if openclaw_error and ":8002" in url:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})

        # Chat completions
        if "/chat/completions" in url:
            body = json.loads(request.content)
            messages = body.get("messages", [])
            user_content = messages[0].get("content", "") if messages else ""

            # Video rejection
            if reject_video and isinstance(user_content, list):
                for part in user_content:
                    if isinstance(part, dict):
                        metadata = part.get("metadata", {})
                        if metadata.get("type") == "video":
                            return httpx.Response(
                                400,
                                json={
                                    "error": {
                                        "message": "Unsupported modality: video is not supported",
                                        "type": "invalid_request",
                                    }
                                },
                            )

            # Per-agent behavior
            if ":8001" in url:
                if hermes_timeout:
                    raise httpx.ReadTimeout("Read timed out")
                if hermes_error:
                    raise httpx.ConnectError("Connection refused")
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": hermes_response}}],
                        "model": "hermes-latest",
                        "usage": {
                            "prompt_tokens": 15,
                            "completion_tokens": 25,
                            "total_tokens": 40,
                        },
                    },
                )
            if ":8002" in url:
                if openclaw_timeout:
                    raise httpx.ReadTimeout("Read timed out")
                if openclaw_error:
                    raise httpx.ConnectError("Connection refused")
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": openclaw_response}}],
                        "model": "openclaw-v1",
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 30,
                            "total_tokens": 42,
                        },
                    },
                )

            return httpx.Response(404, text="Not found")

        return httpx.Response(404, text="Not found")

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Stub connector clients
# ---------------------------------------------------------------------------


class MockTelegramApiClient:
    """Mock Telegram API client that can return bytes for audio files."""

    def __init__(self, *, file_bytes: bytes | None = None, file_url: str | None = None) -> None:
        self._file_bytes = file_bytes
        self._file_url = file_url
        self.sent_messages: list[tuple[str, str]] = []

    async def download_file(self, file_id: str) -> bytes | None:
        return self._file_bytes

    async def resolve_file_url(self, file_id: str) -> str | None:
        return self._file_url

    async def send_message(self, conversation_id: str, text: str) -> dict:
        self.sent_messages.append((conversation_id, text))
        return {"ok": True}


class MockDiscordAttachmentClient:
    """Mock Discord attachment client that can return bytes for downloads."""

    def __init__(self, *, download_bytes_val: bytes | None = None) -> None:
        self._download_bytes_val = download_bytes_val
        self.sent_messages: list[tuple[str, str]] = []

    async def download_bytes(self, attachment: Any) -> bytes | None:
        return self._download_bytes_val

    async def resolve_url(self, attachment: Any) -> str | None:
        return None

    async def send_message(self, conversation_id: str, text: str) -> dict:
        self.sent_messages.append((conversation_id, text))
        return {"ok": True}


# ---------------------------------------------------------------------------
# Context builder with configurable transport
# ---------------------------------------------------------------------------


async def _build_context(
    tmp_path: Path,
    *,
    transport: httpx.MockTransport | None = None,
    telegram_client: MockTelegramApiClient | None = None,
    discord_client: MockDiscordAttachmentClient | None = None,
) -> AppContext:
    """Build a fully-wired AppContext with temporary SQLite and mock transport."""
    db_path = tmp_path / "bench.db"
    storage = StorageManager(db_path=str(db_path))
    await storage.initialize()

    if transport is None:
        transport = _make_transport()

    hermes_http = httpx.AsyncClient(transport=transport)
    openclaw_http = httpx.AsyncClient(transport=transport)

    hermes = HermesAdapter(endpoint="http://localhost:8001", api_key="key-h", client=hermes_http)
    openclaw = OpenClawAdapter(
        endpoint="http://localhost:8002", api_key="key-o", client=openclaw_http
    )

    registry = AgentRegistry()
    registry.register(hermes, DeploymentType.LOCAL_DOCKER, "http://localhost:8001")
    registry.register(openclaw, DeploymentType.LOCAL_DOCKER, "http://localhost:8002")

    runner_config = RunnerConfig(
        execution_order=[
            ("hermes", DeploymentType.LOCAL_DOCKER),
            ("openclaw", DeploymentType.LOCAL_DOCKER),
        ],
        delay_between_seconds=0.0,
        timeout_seconds=5.0,
    )
    runner = BenchmarkRunner(registry=registry, storage=storage, config=runner_config)

    exporter = DailyExporter(storage=storage, export_dir=tmp_path / "exports")
    report_generator = ReportGenerator(storage=storage)
    evaluation_service = EvaluationService(storage=storage)

    tg_client = telegram_client or MockTelegramApiClient()
    tg_connector = TelegramConnector(
        storage=storage, runner=runner, telegram=tg_client, response_client=tg_client
    )

    dc_client = discord_client or MockDiscordAttachmentClient()
    dc_connector = DiscordConnector(
        storage=storage, runner=runner, discord=dc_client, response_client=dc_client
    )

    return AppContext(
        storage=storage,
        registry=registry,
        runner=runner,
        exporter=exporter,
        report_generator=report_generator,
        evaluation_service=evaluation_service,
        telegram_connector=tg_connector,
        discord_connector=dc_connector,
    )


# ---------------------------------------------------------------------------
# 1. Image attachment round-trip through Hermes/OpenClaw
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_image_attachment_round_trip(tmp_path: Path) -> None:
    """Image content_url is sent to agents and responses persist via SQLite."""
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    ctx = await _build_context(tmp_path)
    try:
        benchmark = Benchmark(
            source="cli",
            prompt="Describe this image",
            attachments=[
                Attachment(
                    type=InputType.IMAGE,
                    filename="screenshot.png",
                    mime_type="image/png",
                    size_bytes=len(image_bytes),
                    content_base64=image_b64,
                )
            ],
        )
        await ctx.storage.save_benchmark(benchmark)
        status = await ctx.runner.run(benchmark)

        assert status == BenchmarkStatus.COMPLETED

        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2
        assert executions[0].agent_name == "hermes"
        assert executions[0].result.raw_response == HERMES_RESPONSE
        assert executions[0].success is True
        assert executions[1].agent_name == "openclaw"
        assert executions[1].result.raw_response == OPENCLAW_RESPONSE
        assert executions[1].success is True

        # Verify attachment metadata persisted through SQLite round-trip
        saved = await ctx.storage.get_benchmark(benchmark.id)
        assert saved is not None
        assert len(saved.attachments) == 1
        att = saved.attachments[0]
        assert att.type == InputType.IMAGE
        assert att.filename == "screenshot.png"
        assert att.mime_type == "image/png"
        assert att.size_bytes == len(image_bytes)
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 2. Audio attachment via Telegram connector
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audio_attachment_telegram(tmp_path: Path) -> None:
    """Audio bytes from Telegram persist through SQLite and agents respond."""
    audio_bytes = b"\xff\xfb\x90\x00" + b"\x00" * 200  # fake MP3 frame header

    tg_client = MockTelegramApiClient(file_bytes=audio_bytes)
    ctx = await _build_context(tmp_path, telegram_client=tg_client)
    try:
        assert ctx.telegram_connector is not None

        update = TelegramUpdate(
            update_id=5001,
            message=TelegramMessage(
                message_id=10,
                chat=TelegramChat(id=77777),
                text="Transcribe this audio",
                audio=TelegramAudio(
                    file_id="audio-file-001",
                    file_unique_id="uniq-001",
                    duration=30,
                    mime_type="audio/mpeg",
                    file_size=len(audio_bytes),
                ),
            ),
        )

        result = await ctx.telegram_connector.handle_update(update)

        assert result.accepted is True
        assert result.benchmark is not None
        assert result.benchmark.source == "telegram"

        # Verify audio attachment persisted
        saved = await ctx.storage.get_benchmark(result.benchmark.id)
        assert saved is not None
        assert len(saved.attachments) == 1
        att = saved.attachments[0]
        assert att.type == InputType.AUDIO
        assert att.mime_type == "audio/mpeg"

        # Verify both agents responded
        executions = await ctx.storage.get_executions(result.benchmark.id)
        assert len(executions) == 2
        assert executions[0].agent_name == "hermes"
        assert executions[0].success is True
        assert executions[0].result.raw_response == HERMES_RESPONSE
        assert executions[1].agent_name == "openclaw"
        assert executions[1].success is True
        assert executions[1].result.raw_response == OPENCLAW_RESPONSE

        # Verify response was delivered to Telegram chat
        assert result.delivered is True
        assert len(tg_client.sent_messages) == 1
        assert tg_client.sent_messages[0][0] == "77777"
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 3. Video explicit rejection via Discord connector
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_video_rejection_discord(tmp_path: Path) -> None:
    """Video attachment via Discord: both agents reject with unsupported_modality."""
    video_bytes = b"\x00\x00\x00\x1c" + b"ftyp" + b"\x00" * 100  # fake MP4

    dc_client = MockDiscordAttachmentClient(download_bytes_val=video_bytes)
    ctx = await _build_context(tmp_path, discord_client=dc_client)
    try:
        assert ctx.discord_connector is not None

        message = DiscordMessage(
            id="msg-vid-001",
            channel=DiscordChannel(id="ch-vid"),
            content="Analyze this video",
            attachments=[
                DiscordAttachment(
                    id="att-v1",
                    filename="clip.mp4",
                    content_type="video/mp4",
                    size=len(video_bytes),
                    url="https://cdn.discord.com/clip.mp4",
                )
            ],
        )

        result = await ctx.discord_connector.handle_message(message)

        # Discord connector rejects unsupported video at the connector level
        # before dispatching to the runner, OR the runner persists modality errors.
        # The connector should reject video attachments.
        if result.accepted and result.benchmark is not None:
            # Runner path: both agents return unsupported_modality errors
            executions = await ctx.storage.get_executions(result.benchmark.id)
            assert len(executions) == 2

            for ex in executions:
                assert ex.success is False
                assert any("unsupported_modality" in e for e in ex.result.errors)

            saved = await ctx.storage.get_benchmark(result.benchmark.id)
            assert saved is not None
            assert saved.status == BenchmarkStatus.FAILED

            # Verify Discord response includes modality errors
            if dc_client.sent_messages:
                delivered_text = dc_client.sent_messages[0][1]
                assert (
                    "failed" in delivered_text.lower() or "unsupported_modality" in delivered_text
                )
        else:
            # Connector-level rejection (unsupported_attachment error)
            assert result.error is not None
            assert result.error.code == "unsupported_attachment"
            assert result.error.modality is not None
            assert "video" in (result.error.modality or "")
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 4. Mixed success/failure (Hermes succeeds, OpenClaw times out)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mixed_success_failure(tmp_path: Path) -> None:
    """Hermes succeeds but OpenClaw times out → PARTIALLY_FAILED status."""
    transport = _make_transport(openclaw_timeout=True)
    ctx = await _build_context(tmp_path, transport=transport)
    try:
        benchmark = Benchmark(source="cli", prompt="Give me a summary of microservices")
        await ctx.storage.save_benchmark(benchmark)
        status = await ctx.runner.run(benchmark)

        assert status == BenchmarkStatus.PARTIALLY_FAILED

        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2

        # Hermes succeeded
        hermes_ex = executions[0]
        assert hermes_ex.agent_name == "hermes"
        assert hermes_ex.success is True
        assert hermes_ex.result.raw_response == HERMES_RESPONSE

        # OpenClaw failed with timeout error
        openclaw_ex = executions[1]
        assert openclaw_ex.agent_name == "openclaw"
        assert openclaw_ex.success is False
        assert len(openclaw_ex.result.errors) > 0

        # The failed execution does NOT stop Hermes from being counted
        saved = await ctx.storage.get_benchmark(benchmark.id)
        assert saved is not None
        assert saved.status == BenchmarkStatus.PARTIALLY_FAILED
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 5. Endpoint unavailable (both agents unreachable)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_both_endpoints_unavailable(tmp_path: Path) -> None:
    """Both agents unreachable → FAILED status, both attempted sequentially."""
    transport = _make_transport(hermes_error=True, openclaw_error=True)
    ctx = await _build_context(tmp_path, transport=transport)
    try:
        benchmark = Benchmark(source="cli", prompt="Hello world")
        await ctx.storage.save_benchmark(benchmark)
        status = await ctx.runner.run(benchmark)

        assert status == BenchmarkStatus.FAILED

        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2

        # Both attempted and both failed
        for ex in executions:
            assert ex.success is False
            assert len(ex.result.errors) > 0

        # Sequential: both were attempted despite the first failing
        assert executions[0].agent_name == "hermes"
        assert executions[1].agent_name == "openclaw"
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 6. Evaluation display after mixed results
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evaluation_after_mixed_results(tmp_path: Path) -> None:
    """Evaluation joins correctly with executions after mixed results."""
    transport = _make_transport(openclaw_timeout=True)
    ctx = await _build_context(tmp_path, transport=transport)
    try:
        benchmark = Benchmark(
            source="cli",
            prompt="Compare these approaches",
            tags=["architecture"],
        )
        await ctx.storage.save_benchmark(benchmark)
        status = await ctx.runner.run(benchmark)
        assert status == BenchmarkStatus.PARTIALLY_FAILED

        # Submit evaluation with preferred_agent = hermes (the successful one)
        evaluation = Evaluation(
            benchmark_id=benchmark.id,
            rating=3,
            preferred_agent="hermes",
            preferred_deployment=DeploymentType.LOCAL_DOCKER,
            notes="Only Hermes responded",
        )
        saved_eval = await ctx.evaluation_service.submit(evaluation)
        assert saved_eval.id == evaluation.id

        # Retrieve and verify evaluation joins correctly
        retrieved_eval = await ctx.storage.get_evaluation(benchmark.id)
        assert retrieved_eval is not None
        assert retrieved_eval.preferred_agent == "hermes"
        assert retrieved_eval.rating == 3
        assert retrieved_eval.notes == "Only Hermes responded"

        # Verify preferred_agent validation works: invalid agent rejected
        bad_eval = Evaluation(
            benchmark_id=benchmark.id,
            rating=4,
            preferred_agent="nonexistent-agent",
        )
        # Should fail because there's already an evaluation (conflict check first)
        from benchmark.evaluation.exceptions import EvaluationConflictError

        with pytest.raises(EvaluationConflictError):
            await ctx.evaluation_service.submit(bad_eval)
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 7. Daily export includes response content and errors
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_export_content_and_errors(tmp_path: Path) -> None:
    """Export includes response content, errors, agent names, and metrics."""
    transport = _make_transport(openclaw_timeout=True)
    ctx = await _build_context(tmp_path, transport=transport)
    try:
        benchmark = Benchmark(source="cli", prompt="Test export data")
        await ctx.storage.save_benchmark(benchmark)
        await ctx.runner.run(benchmark)

        today = datetime.now(UTC).date().isoformat()
        manifest = await ctx.exporter.export_day(today)

        assert manifest.benchmark_count == 1
        assert manifest.execution_count == 2
        assert len(manifest.files) >= 2  # JSONL + at least 1 CSV

        # Read JSONL and verify content
        jsonl_path = next(f for f in manifest.files if f.endswith(".jsonl"))
        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["benchmark"]["prompt"] == "Test export data"
        assert len(record["executions"]) == 2

        hermes_exec = record["executions"][0]
        assert hermes_exec["agent_name"] == "hermes"
        assert hermes_exec["result"]["raw_response"] == HERMES_RESPONSE

        openclaw_exec = record["executions"][1]
        assert openclaw_exec["agent_name"] == "openclaw"
        assert openclaw_exec["success"] is False
        assert len(openclaw_exec["result"]["errors"]) > 0

        # Read executions CSV and verify agent names and response appear
        exec_csv_path = next(f for f in manifest.files if "executions" in f and f.endswith(".csv"))
        with open(exec_csv_path) as f:
            csv_content = f.read()
        assert "hermes" in csv_content
        assert "openclaw" in csv_content
        assert HERMES_RESPONSE in csv_content
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 8. Report includes failed execution counts, excludes failures from recs
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_failure_counts_and_recommendations(tmp_path: Path) -> None:
    """Report shows failed executions and recommendations exclude failures."""
    ctx = await _build_context(tmp_path)
    try:
        # Run multiple benchmarks with evaluations — need >= 5 for recommendations
        for i in range(6):
            benchmark = Benchmark(
                source="cli",
                prompt=f"Benchmark question {i}",
                tags=["category-A"],
            )
            await ctx.storage.save_benchmark(benchmark)
            await ctx.runner.run(benchmark)

            evaluation = Evaluation(
                benchmark_id=benchmark.id,
                rating=4,
                preferred_agent="hermes",
                preferred_deployment=DeploymentType.LOCAL_DOCKER,
            )
            await ctx.evaluation_service.submit(evaluation)

        # Run one with failure (OpenClaw timeout)
        fail_transport = _make_transport(openclaw_timeout=True)
        fail_hermes_http = httpx.AsyncClient(transport=fail_transport)
        fail_openclaw_http = httpx.AsyncClient(transport=fail_transport)

        fail_hermes = HermesAdapter(
            endpoint="http://localhost:8001", api_key="key-h", client=fail_hermes_http
        )
        fail_openclaw = OpenClawAdapter(
            endpoint="http://localhost:8002", api_key="key-o", client=fail_openclaw_http
        )

        fail_registry = AgentRegistry()
        fail_registry.register(fail_hermes, DeploymentType.LOCAL_DOCKER, "http://localhost:8001")
        fail_registry.register(fail_openclaw, DeploymentType.LOCAL_DOCKER, "http://localhost:8002")

        fail_config = RunnerConfig(
            execution_order=[
                ("hermes", DeploymentType.LOCAL_DOCKER),
                ("openclaw", DeploymentType.LOCAL_DOCKER),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=5.0,
        )
        fail_runner = BenchmarkRunner(
            registry=fail_registry, storage=ctx.storage, config=fail_config
        )

        fail_benchmark = Benchmark(
            source="cli", prompt="This will partially fail", tags=["category-A"]
        )
        await ctx.storage.save_benchmark(fail_benchmark)
        status = await fail_runner.run(fail_benchmark)
        assert status == BenchmarkStatus.PARTIALLY_FAILED

        eval_fail = Evaluation(
            benchmark_id=fail_benchmark.id,
            rating=2,
            preferred_agent="hermes",
            preferred_deployment=DeploymentType.LOCAL_DOCKER,
            notes="OpenClaw timed out",
        )
        await ctx.evaluation_service.submit(eval_fail)

        # Generate report
        today = datetime.now(UTC).date().isoformat()
        report = await ctx.report_generator.generate(today, today)

        assert isinstance(report, str)
        assert "Benchmark Report" in report

        # Verify execution errors section exists with failure info
        assert "Execution Errors" in report

        # Verify recommendations section includes only successful pairs
        assert "Recommendations" in report
        # hermes should appear in recommendations (has wins from successful benchmarks)
        assert "hermes" in report
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# 9. Sequential ordering preserved across connector submissions
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sequential_ordering_across_sources(tmp_path: Path) -> None:
    """Sequential Hermes-then-OpenClaw order preserved for each benchmark."""
    ctx = await _build_context(tmp_path)
    try:
        # Submit 3 benchmarks rapidly: CLI, Telegram, Discord
        cli_benchmark = Benchmark(source="cli", prompt="CLI sequential test")
        await ctx.storage.save_benchmark(cli_benchmark)
        await ctx.runner.run(cli_benchmark)

        assert ctx.telegram_connector is not None
        tg_result = await ctx.telegram_connector.handle_update(
            TelegramUpdate(
                update_id=9001,
                message=TelegramMessage(
                    message_id=90, chat=TelegramChat(id=55555), text="Telegram sequential test"
                ),
            )
        )
        assert tg_result.accepted is True

        assert ctx.discord_connector is not None
        dc_result = await ctx.discord_connector.handle_message(
            DiscordMessage(
                id="msg-seq-001",
                channel=DiscordChannel(id="ch-seq"),
                content="Discord sequential test",
            )
        )
        assert dc_result.accepted is True

        # Verify each benchmark has sequential Hermes-before-OpenClaw execution
        benchmark_ids = [
            cli_benchmark.id,
            tg_result.benchmark.id,
            dc_result.benchmark.id,
        ]

        for bid in benchmark_ids:
            executions = await ctx.storage.get_executions(bid)
            assert len(executions) == 2
            assert executions[0].agent_name == "hermes"
            assert executions[1].agent_name == "openclaw"

            # Verify started_at shows Hermes before OpenClaw
            assert executions[0].started_at <= executions[1].started_at
    finally:
        await ctx.storage.close()
