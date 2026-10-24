"""Direct async tests for CLI command helper functions.

The Typer CliRunner does not reliably capture coverage inside asyncio.run()
coroutines. These tests call the async helpers and sync commands directly
to cover the branches that runner.invoke misses.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import typer

from benchmark.agents.registry import AgentRegistry
from benchmark.cli.commands.report import _generate_report, report_command
from benchmark.cli.commands.run import _run_benchmark, run_command
from benchmark.cli.commands.status import _fetch_status, status_command
from benchmark.cli.commands.telegram import _run_bot, telegram_command
from benchmark.cli.wiring import AppContext, _build_json_agent_specs
from benchmark.config.settings import Settings
from benchmark.evaluation.service import EvaluationService
from benchmark.export.daily import DailyExporter
from benchmark.models.domain import Benchmark
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _make_real_context(tmp_path: Path) -> AppContext:
    """Build a real AppContext backed by a temporary SQLite database."""
    storage = StorageManager(db_path=str(tmp_path / "test.db"))
    await storage.initialize()
    registry = AgentRegistry()
    runner_config = RunnerConfig(execution_order=[], delay_between_seconds=0, timeout_seconds=5)
    runner = BenchmarkRunner(registry=registry, storage=storage, config=runner_config)
    return AppContext(
        storage=storage,
        registry=registry,
        runner=runner,
        exporter=DailyExporter(storage=storage, export_dir=tmp_path / "exports"),
        report_generator=ReportGenerator(storage=storage),
        evaluation_service=EvaluationService(storage=storage),
    )


def _ctx_patcher(ctx: AppContext):
    """Return a coroutine-returning mock for create_context that yields ctx."""

    async def _create(_settings=None):
        return ctx

    return patch("benchmark.cli.wiring.create_context", side_effect=_create)


# ---------------------------------------------------------------------------
# _generate_report — covers report.py lines 25-29
# ---------------------------------------------------------------------------


class TestGenerateReportAsync:
    async def test_returns_markdown_report_string(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        try:
            with patch("benchmark.cli.commands.report.create_context", return_value=ctx):
                report = await _generate_report(7)
        finally:
            await ctx.storage.close()
        assert "Benchmark Report" in report

    async def test_report_with_30_days(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        try:
            with patch("benchmark.cli.commands.report.create_context", return_value=ctx):
                report = await _generate_report(30)
        finally:
            await ctx.storage.close()
        assert "Benchmark Report" in report

    async def test_report_with_90_days(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        try:
            with patch("benchmark.cli.commands.report.create_context", return_value=ctx):
                report = await _generate_report(90)
        finally:
            await ctx.storage.close()
        assert "Benchmark Report" in report

    async def test_storage_closed_after_generate(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        close_calls: list[bool] = []
        original_close = ctx.storage.close

        async def _tracked_close():
            close_calls.append(True)
            await original_close()

        ctx.storage.close = _tracked_close  # type: ignore[method-assign]
        with patch("benchmark.cli.commands.report.create_context", return_value=ctx):
            await _generate_report(7)
        assert close_calls, "storage.close() must be called in the finally block"


# ---------------------------------------------------------------------------
# report_command — covers report.py lines 46-52 (exception path)
# ---------------------------------------------------------------------------


class TestReportCommand:
    def test_exception_in_generate_exits_nonzero(self, tmp_path):
        async def _raise(_days):
            raise RuntimeError("db gone")

        with (
            patch("benchmark.cli.commands.report._generate_report", side_effect=_raise),
            pytest.raises(typer.Exit) as exc_info,
        ):
            report_command(7)
        assert exc_info.value.exit_code == 1

    def test_typer_exit_is_reraised_not_swallowed(self, tmp_path):
        async def _exit(_days):
            raise typer.Exit(code=2)

        with (
            patch("benchmark.cli.commands.report._generate_report", side_effect=_exit),
            pytest.raises(typer.Exit) as exc_info,
        ):
            report_command(7)
        assert exc_info.value.exit_code == 2


# ---------------------------------------------------------------------------
# _run_benchmark — covers run.py lines 27-29
# ---------------------------------------------------------------------------


class TestRunBenchmarkAsync:
    async def test_returns_benchmark_id(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        try:
            with patch("benchmark.cli.commands.run.create_context", return_value=ctx):
                benchmark_id = await _run_benchmark("Write a hello world", [])
        finally:
            await ctx.storage.close()
        assert len(benchmark_id) == 26  # ULID length

    async def test_saves_benchmark_with_tags(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        db_path = str(tmp_path / "test.db")
        with patch("benchmark.cli.commands.run.create_context", return_value=ctx):
            benchmark_id = await _run_benchmark("Explain Docker", ["devops", "research"])
        # _run_benchmark closes the storage in finally; re-open to verify
        from benchmark.storage.manager import BenchmarkFilters

        verify = StorageManager(db_path=db_path)
        await verify.initialize()
        try:
            benchmarks = await verify.list_benchmarks(BenchmarkFilters(limit=50))
        finally:
            await verify.close()
        assert any(b.id == benchmark_id for b in benchmarks)
        match = next(b for b in benchmarks if b.id == benchmark_id)
        assert "devops" in match.tags
        assert "research" in match.tags

    async def test_storage_closed_after_run(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        close_calls: list[bool] = []
        original_close = ctx.storage.close

        async def _tracked_close():
            close_calls.append(True)
            await original_close()

        ctx.storage.close = _tracked_close  # type: ignore[method-assign]
        with patch("benchmark.cli.commands.run.create_context", return_value=ctx):
            await _run_benchmark("test", [])
        assert close_calls


# ---------------------------------------------------------------------------
# run_command — covers run.py lines 59-63 (exception path)
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_exception_in_run_exits_nonzero(self):
        async def _raise(_prompt, _tags):
            raise RuntimeError("network error")

        with (
            patch("benchmark.cli.commands.run._run_benchmark", side_effect=_raise),
            pytest.raises(typer.Exit) as exc_info,
        ):
            run_command("some prompt")
        assert exc_info.value.exit_code == 1


# ---------------------------------------------------------------------------
# _fetch_status — covers status.py lines 28-29 and line 43 (truncation)
# ---------------------------------------------------------------------------


class TestFetchStatusAsync:
    async def test_no_benchmarks_message(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        try:
            with patch("benchmark.cli.commands.status.create_context", return_value=ctx):
                output = await _fetch_status()
        finally:
            await ctx.storage.close()
        assert "No benchmarks found" in output

    async def test_shows_benchmarks_after_insert(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        try:
            benchmark = Benchmark(source="cli", prompt="Test prompt for status", tags=[])
            await ctx.storage.save_benchmark(benchmark)
            with patch("benchmark.cli.commands.status.create_context", return_value=ctx):
                output = await _fetch_status()
        finally:
            await ctx.storage.close()
        assert "Test prompt for status" in output

    async def test_long_prompt_is_truncated(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        long_prompt = "A" * 200
        try:
            benchmark = Benchmark(source="cli", prompt=long_prompt, tags=[])
            await ctx.storage.save_benchmark(benchmark)
            with patch("benchmark.cli.commands.status.create_context", return_value=ctx):
                output = await _fetch_status()
        finally:
            await ctx.storage.close()
        assert "..." in output
        assert long_prompt not in output

    async def test_storage_closed_after_status(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        close_calls: list[bool] = []
        original_close = ctx.storage.close

        async def _tracked_close():
            close_calls.append(True)
            await original_close()

        ctx.storage.close = _tracked_close  # type: ignore[method-assign]
        with patch("benchmark.cli.commands.status.create_context", return_value=ctx):
            await _fetch_status()
        assert close_calls


# ---------------------------------------------------------------------------
# status_command — covers status.py lines 59-63 (exception path)
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_exception_in_fetch_exits_nonzero(self):
        async def _raise():
            raise RuntimeError("db locked")

        with (
            patch("benchmark.cli.commands.status._fetch_status", side_effect=_raise),
            pytest.raises(typer.Exit) as exc_info,
        ):
            status_command()
        assert exc_info.value.exit_code == 1


# ---------------------------------------------------------------------------
# _run_bot — covers telegram.py lines 40-54
# ---------------------------------------------------------------------------


class TestRunBotAsync:
    async def test_run_bot_with_allowed_ids_prints_restriction_message(self, tmp_path, capsys):
        ctx = await _make_real_context(tmp_path)
        messages: list[str] = []

        async def _fake_run_polling(**kwargs):
            pass

        with (
            patch("benchmark.cli.commands.telegram.create_context", return_value=ctx),
            patch("benchmark.bots.telegram.run_polling", new=_fake_run_polling),
            patch("benchmark.cli.commands.telegram.typer.echo", side_effect=messages.append),
        ):
            await _run_bot("token", frozenset({"123456"}))

        joined = "\n".join(str(m) for m in messages)
        assert "polling" in joined.lower()
        assert "123456" in joined
        await ctx.storage.close()

    async def test_run_bot_without_allowed_ids_warns(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        messages: list[str] = []

        async def _fake_run_polling(**kwargs):
            pass

        with (
            patch("benchmark.cli.commands.telegram.create_context", return_value=ctx),
            patch("benchmark.bots.telegram.run_polling", new=_fake_run_polling),
            patch("benchmark.cli.commands.telegram.typer.echo", side_effect=messages.append),
        ):
            await _run_bot("token", frozenset())

        joined = "\n".join(str(m) for m in messages)
        assert "warning" in joined.lower() or "all chats" in joined.lower()
        await ctx.storage.close()

    async def test_run_bot_closes_storage(self, tmp_path):
        ctx = await _make_real_context(tmp_path)
        close_calls: list[bool] = []
        original_close = ctx.storage.close

        async def _tracked_close():
            close_calls.append(True)
            await original_close()

        ctx.storage.close = _tracked_close  # type: ignore[method-assign]

        async def _fake_run_polling(**kwargs):
            pass

        with (
            patch("benchmark.cli.commands.telegram.create_context", return_value=ctx),
            patch("benchmark.bots.telegram.run_polling", new=_fake_run_polling),
            patch("benchmark.cli.commands.telegram.typer.echo"),
        ):
            await _run_bot("token", frozenset())

        assert close_calls


# ---------------------------------------------------------------------------
# telegram_command — covers telegram.py lines 73-78 (exception path)
# ---------------------------------------------------------------------------


class TestTelegramCommand:
    def test_exception_exits_nonzero(self):
        async def _raise(_token, _ids):
            raise RuntimeError("connection refused")

        with (
            patch("benchmark.cli.commands.telegram._run_bot", side_effect=_raise),
            pytest.raises(typer.Exit) as exc_info,
        ):
            telegram_command("valid:TOKEN", "111")
        assert exc_info.value.exit_code == 1

    def test_keyboard_interrupt_exits_cleanly(self):
        async def _interrupt(_token, _ids):
            raise KeyboardInterrupt

        with patch("benchmark.cli.commands.telegram._run_bot", side_effect=_interrupt):
            telegram_command("valid:TOKEN", "111")  # should not raise

    def test_no_allowed_chat_ids_refuses_to_start(self):
        with pytest.raises(typer.Exit) as exc_info:
            telegram_command("valid:TOKEN", "")
        assert exc_info.value.exit_code == 1

    def test_allow_all_chats_opt_in_starts(self):
        async def _interrupt(_token, _ids):
            raise KeyboardInterrupt

        with patch("benchmark.cli.commands.telegram._run_bot", side_effect=_interrupt):
            telegram_command("valid:TOKEN", "", allow_all_chats=True)  # should not raise


# ---------------------------------------------------------------------------
# _build_json_agent_specs — covers wiring.py lines 189-190 (non-dict item)
# ---------------------------------------------------------------------------


class TestBuildJsonAgentSpecsEdgeCases:
    def test_list_with_non_dict_items_skips_and_continues(self, tmp_path):
        """A JSON array containing non-dict items (strings, ints) should skip
        those items and still process valid dict entries that follow."""
        import json

        items = [
            "not a dict",
            42,
            {"name": "valid", "endpoint": "http://localhost:9000/v1", "model": "llama3"},
        ]
        agents_json = json.dumps(items)

        env = {
            "BENCH_DB_PATH": str(tmp_path / "test.db"),
            "BENCH_HERMES_API_KEY": "",
            "BENCH_OPENCLAW_API_KEY": "",
            "BENCH_NVIDIA_API_KEY": "",
            "BENCH_SIGNING_KEY": "",
            "BENCH_TELEGRAM_BOT_TOKEN": "",
            "BENCH_DISCORD_BOT_TOKEN": "",
            "BENCH_DELAY_SECONDS": "0",
            "BENCH_TIMEOUT_SECONDS": "5",
            "BENCH_AGENTS_JSON": agents_json,
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            signing_key = settings.signing_key.get_secret_value() or None
            specs = _build_json_agent_specs(settings, signing_key)

        assert len(specs) == 1
        assert specs[0].name == "valid"

    def test_mixed_valid_and_invalid_items(self, tmp_path):
        """Only dict items with required fields produce specs; others are silently dropped."""
        import json

        items = [
            None,
            {"name": "a", "endpoint": "http://a/v1", "model": "m1"},
            "string",
            {"name": "b"},  # missing endpoint and model
            {"name": "c", "endpoint": "http://c/v1", "model": "m3"},
        ]
        agents_json = json.dumps(items)

        env = {
            "BENCH_DB_PATH": str(tmp_path / "test.db"),
            "BENCH_HERMES_API_KEY": "",
            "BENCH_OPENCLAW_API_KEY": "",
            "BENCH_NVIDIA_API_KEY": "",
            "BENCH_SIGNING_KEY": "",
            "BENCH_TELEGRAM_BOT_TOKEN": "",
            "BENCH_DISCORD_BOT_TOKEN": "",
            "BENCH_DELAY_SECONDS": "0",
            "BENCH_TIMEOUT_SECONDS": "5",
            "BENCH_AGENTS_JSON": agents_json,
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            signing_key = settings.signing_key.get_secret_value() or None
            specs = _build_json_agent_specs(settings, signing_key)

        names = [s.name for s in specs]
        assert names == ["a", "c"]
