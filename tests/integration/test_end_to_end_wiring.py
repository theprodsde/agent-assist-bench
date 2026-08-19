"""End-to-end wiring integration test.

Exercises the confirmed order of configured agent executions with Hermes and
OpenClaw endpoints. Verifies that:
- Every successful execution returns its actual response
- Every attachment is transported or explicitly rejected
- Every rejection is persisted and surfaced
- The sequential runner and local mock-agent flow form the integration seam

Uses httpx mock transports to return deterministic responses for text prompts
and explicit unsupported-modality errors for video attachments.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from benchmark.agents.hermes import HermesAdapter
from benchmark.agents.openclaw import OpenClawAdapter
from benchmark.agents.registry import AgentRegistry
from benchmark.cli.wiring import AppContext
from benchmark.connectors.discord import (
    DiscordChannel,
    DiscordConnector,
    DiscordMessage,
)
from benchmark.connectors.telegram import (
    TelegramChat,
    TelegramConnector,
    TelegramMessage,
    TelegramUpdate,
)
from benchmark.models.domain import (
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    InputType,
)
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Mock httpx transport returning deterministic agent responses
# ---------------------------------------------------------------------------

HERMES_TEXT_RESPONSE = "Hermes processed your request successfully."
OPENCLAW_TEXT_RESPONSE = "OpenClaw completed the analysis."

UNSUPPORTED_MODALITY_BODY = json.dumps(
    {
        "error": {
            "message": "Unsupported modality: video is not supported",
            "type": "invalid_request",
        }
    }
)


def _mock_agent_handler(request: httpx.Request) -> httpx.Response:
    """Deterministic mock for both Hermes and OpenClaw endpoints."""
    url = str(request.url)
    body = json.loads(request.content)

    # Health check endpoint
    if "/models" in url:
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})

    # Chat completions endpoint
    if "/chat/completions" in url:
        messages = body.get("messages", [])
        user_content = messages[0].get("content", "") if messages else ""

        # Check for video attachment → unsupported modality error
        if isinstance(user_content, list):
            # Multimodal content parts - if there are video attachments, reject
            for part in user_content:
                if isinstance(part, dict) and part.get("metadata", {}).get("type") == "video":
                    return httpx.Response(400, text=UNSUPPORTED_MODALITY_BODY)

        # Determine which agent based on URL
        if ":8001" in url:
            response_text = HERMES_TEXT_RESPONSE
        elif ":8002" in url:
            response_text = OPENCLAW_TEXT_RESPONSE
        else:
            response_text = "Unknown agent response"

        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": response_text}}],
                "model": "test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    return httpx.Response(404, text="Not found")


# ---------------------------------------------------------------------------
# Stub clients for connectors
# ---------------------------------------------------------------------------


class MockTelegramApiClient:
    """Mock Telegram API client that provides URL-only mode."""

    async def download_file(self, file_id: str) -> bytes | None:
        return None

    async def resolve_file_url(self, file_id: str) -> str | None:
        return None

    async def send_message(self, conversation_id: str, text: str) -> dict:
        return {"ok": True}


class MockDiscordAttachmentClient:
    """Mock Discord attachment client that provides URL-only mode."""

    async def download_bytes(self, attachment: object) -> bytes | None:
        return None

    async def resolve_url(self, attachment: object) -> str | None:
        return None

    async def send_message(self, conversation_id: str, text: str) -> dict:
        return {"ok": True}


# ---------------------------------------------------------------------------
# Helper: build a fully-wired AppContext with temp SQLite and mock transports
# ---------------------------------------------------------------------------


async def _build_context(tmp_path: Path) -> AppContext:
    """Create AppContext with temp DB and mock httpx transport for both agents."""
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path=str(db_path))
    await storage.initialize()

    mock_transport = httpx.MockTransport(_mock_agent_handler)

    # Create agents with mock transport
    hermes_client = httpx.AsyncClient(transport=mock_transport)
    openclaw_client = httpx.AsyncClient(transport=mock_transport)

    hermes = HermesAdapter(
        endpoint="http://localhost:8001",
        api_key="test-hermes-key",
        client=hermes_client,
    )
    openclaw = OpenClawAdapter(
        endpoint="http://localhost:8002",
        api_key="test-openclaw-key",
        client=openclaw_client,
    )

    registry = AgentRegistry()
    registry.register(hermes, DeploymentType.LOCAL_DOCKER, "http://localhost:8001")
    registry.register(openclaw, DeploymentType.LOCAL_DOCKER, "http://localhost:8002")

    execution_order = [
        ("hermes", DeploymentType.LOCAL_DOCKER),
        ("openclaw", DeploymentType.LOCAL_DOCKER),
    ]
    runner_config = RunnerConfig(
        execution_order=execution_order,
        delay_between_seconds=0.0,
        timeout_seconds=10.0,
    )
    runner = BenchmarkRunner(registry=registry, storage=storage, config=runner_config)

    from benchmark.evaluation.service import EvaluationService
    from benchmark.export.daily import DailyExporter

    exporter = DailyExporter(storage=storage, export_dir=tmp_path / "exports")
    report_generator = ReportGenerator(storage=storage)
    evaluation_service = EvaluationService(storage=storage)

    # Wire connectors
    telegram_client = MockTelegramApiClient()
    telegram_connector = TelegramConnector(
        storage=storage,
        runner=runner,
        telegram=telegram_client,
        response_client=telegram_client,
    )

    discord_client = MockDiscordAttachmentClient()
    discord_connector = DiscordConnector(
        storage=storage,
        runner=runner,
        discord=discord_client,
        response_client=discord_client,
    )

    return AppContext(
        storage=storage,
        registry=registry,
        runner=runner,
        exporter=exporter,
        report_generator=report_generator,
        evaluation_service=evaluation_service,
        telegram_connector=telegram_connector,
        discord_connector=discord_connector,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cli_runner_path_persists_benchmarks(tmp_path: Path) -> None:
    """Submit a benchmark through the CLI runner path and verify persistence."""
    ctx = await _build_context(tmp_path)
    try:
        benchmark = Benchmark(source="cli", prompt="Explain async/await in Python")
        await ctx.storage.save_benchmark(benchmark)

        status = await ctx.runner.run(benchmark)

        assert status == BenchmarkStatus.COMPLETED
        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2

        hermes_exec = executions[0]
        assert hermes_exec.agent_name == "hermes"
        assert hermes_exec.success is True
        assert hermes_exec.result.raw_response == HERMES_TEXT_RESPONSE

        openclaw_exec = executions[1]
        assert openclaw_exec.agent_name == "openclaw"
        assert openclaw_exec.success is True
        assert openclaw_exec.result.raw_response == OPENCLAW_TEXT_RESPONSE
    finally:
        await ctx.storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_connector_submits_and_persists(tmp_path: Path) -> None:
    """Submit a benchmark through TelegramConnector and verify persistence."""
    ctx = await _build_context(tmp_path)
    try:
        assert ctx.telegram_connector is not None

        update = TelegramUpdate(
            update_id=1001,
            message=TelegramMessage(
                message_id=1,
                chat=TelegramChat(id=12345),
                text="Describe the Observer pattern",
            ),
        )

        result = await ctx.telegram_connector.handle_update(update)

        assert result.accepted is True
        assert result.benchmark is not None
        assert result.benchmark.source == "telegram"

        # Verify persistence
        saved = await ctx.storage.get_benchmark(result.benchmark.id)
        assert saved is not None
        assert saved.source == "telegram"
        assert saved.prompt == "Describe the Observer pattern"

        # Verify sequential executions
        executions = await ctx.storage.get_executions(result.benchmark.id)
        assert len(executions) == 2
        assert executions[0].agent_name == "hermes"
        assert executions[0].success is True
        assert executions[0].result.raw_response == HERMES_TEXT_RESPONSE
        assert executions[1].agent_name == "openclaw"
        assert executions[1].success is True
        assert executions[1].result.raw_response == OPENCLAW_TEXT_RESPONSE
    finally:
        await ctx.storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discord_connector_submits_and_persists(tmp_path: Path) -> None:
    """Submit a benchmark through DiscordConnector and verify persistence."""
    ctx = await _build_context(tmp_path)
    try:
        assert ctx.discord_connector is not None

        message = DiscordMessage(
            id="msg-2001",
            channel=DiscordChannel(id="ch-100"),
            content="Explain dependency injection",
        )

        result = await ctx.discord_connector.handle_message(message)

        assert result.accepted is True
        assert result.benchmark is not None
        assert result.benchmark.source == "discord"

        # Verify persistence
        saved = await ctx.storage.get_benchmark(result.benchmark.id)
        assert saved is not None
        assert saved.source == "discord"
        assert saved.prompt == "Explain dependency injection"

        # Verify sequential executions
        executions = await ctx.storage.get_executions(result.benchmark.id)
        assert len(executions) == 2
        assert executions[0].agent_name == "hermes"
        assert executions[0].success is True
        assert executions[0].result.raw_response == HERMES_TEXT_RESPONSE
        assert executions[1].agent_name == "openclaw"
        assert executions[1].success is True
        assert executions[1].result.raw_response == OPENCLAW_TEXT_RESPONSE
    finally:
        await ctx.storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unsupported_modality_does_not_stop_later_agents(tmp_path: Path) -> None:
    """Video attachment causes modality rejection but later agents still execute.

    Verifies that unsupported-modality errors from one agent don't stop the
    sequential pipeline from continuing to subsequent agents.
    """
    ctx = await _build_context(tmp_path)
    try:
        benchmark = Benchmark(
            source="cli",
            prompt="Analyze this video content",
            attachments=[
                Attachment(
                    type=InputType.VIDEO,
                    filename="clip.mp4",
                    mime_type="video/mp4",
                    size_bytes=1024,
                    content_base64="dGVzdHZpZGVv",
                )
            ],
        )
        await ctx.storage.save_benchmark(benchmark)

        status = await ctx.runner.run(benchmark)

        # Both agents reject video → both fail → FAILED status
        assert status == BenchmarkStatus.FAILED
        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2

        # Both should have modality errors persisted
        for ex in executions:
            assert ex.success is False
            assert any("unsupported_modality" in e for e in ex.result.errors)

        # Crucially, BOTH agents ran — the first rejection did not stop the second
        assert executions[0].agent_name == "hermes"
        assert executions[1].agent_name == "openclaw"
    finally:
        await ctx.storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_generator_produces_output_from_persisted_data(tmp_path: Path) -> None:
    """Report generator produces valid markdown from persisted benchmark data."""
    ctx = await _build_context(tmp_path)
    try:
        # Create and run a benchmark to populate storage
        benchmark = Benchmark(
            source="cli",
            prompt="Explain SOLID principles",
            tags=["software-design"],
        )
        await ctx.storage.save_benchmark(benchmark)
        await ctx.runner.run(benchmark)

        # Add an evaluation so the report has data to work with
        from benchmark.models.domain import Evaluation

        evaluation = Evaluation(
            benchmark_id=benchmark.id,
            rating=4,
            preferred_agent="hermes",
            preferred_deployment=DeploymentType.LOCAL_DOCKER,
            notes="Good explanation",
        )
        await ctx.storage.save_evaluation(evaluation)

        # Generate report using the benchmark's actual UTC creation date
        from datetime import UTC, datetime

        utc_date = datetime.now(UTC).date().isoformat()
        report = await ctx.report_generator.generate(utc_date, utc_date)

        assert isinstance(report, str)
        assert "Benchmark Report" in report
        assert "hermes" in report
        assert "openclaw" in report
    finally:
        await ctx.storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_three_sources_in_same_database(tmp_path: Path) -> None:
    """All sources (CLI, Telegram, Discord) coexist in the same SQLite database.

    Verifies correct source attribution and sequential execution records.
    """
    ctx = await _build_context(tmp_path)
    try:
        # 1. CLI source
        cli_benchmark = Benchmark(source="cli", prompt="CLI question")
        await ctx.storage.save_benchmark(cli_benchmark)
        await ctx.runner.run(cli_benchmark)

        # 2. Telegram source
        assert ctx.telegram_connector is not None
        tg_update = TelegramUpdate(
            update_id=2001,
            message=TelegramMessage(
                message_id=2,
                chat=TelegramChat(id=99999),
                text="Telegram question",
            ),
        )
        tg_result = await ctx.telegram_connector.handle_update(tg_update)
        assert tg_result.accepted is True

        # 3. Discord source
        assert ctx.discord_connector is not None
        dc_message = DiscordMessage(
            id="msg-3001",
            channel=DiscordChannel(id="ch-200"),
            content="Discord question",
        )
        dc_result = await ctx.discord_connector.handle_message(dc_message)
        assert dc_result.accepted is True

        # Verify all three benchmarks are stored with correct sources
        from benchmark.storage.manager import BenchmarkFilters

        all_benchmarks = await ctx.storage.list_benchmarks(BenchmarkFilters(limit=10))
        assert len(all_benchmarks) == 3

        sources = {b.source for b in all_benchmarks}
        assert sources == {"cli", "telegram", "discord"}

        # Verify each has 2 executions (hermes + openclaw)
        for b in all_benchmarks:
            executions = await ctx.storage.get_executions(b.id)
            assert len(executions) == 2
            assert executions[0].agent_name == "hermes"
            assert executions[1].agent_name == "openclaw"
    finally:
        await ctx.storage.close()
