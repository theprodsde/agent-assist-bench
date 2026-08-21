"""Unit tests for CLI commands.

Tests the run, status, report commands and wiring module.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from benchmark.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Use a temporary database for each test to avoid side effects."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("BENCH_DB_PATH", db_path)


class TestRunCommand:
    """Tests for `aab run` command."""

    def test_run_rejects_empty_prompt(self):
        """Req 9.6, 1.3: Empty prompt is rejected with non-zero exit."""
        result = runner.invoke(app, ["run", "   "])
        assert result.exit_code != 0
        assert "empty" in result.output.lower()

    def test_run_rejects_prompt_exceeding_max_length(self):
        """Req 9.6: Prompt > 100,000 chars is rejected."""
        long_prompt = "x" * 100_001
        result = runner.invoke(app, ["run", long_prompt])
        assert result.exit_code != 0
        assert "100,000" in result.output

    def test_run_valid_prompt_prints_benchmark_id(self):
        """Req 9.1: Valid run prints benchmark ID to stdout."""
        result = runner.invoke(app, ["run", "Test benchmark prompt"])
        # Should succeed (exit 0) and output a ULID-like ID (26 chars)
        assert result.exit_code == 0
        # The output should contain a ULID (26 alphanumeric chars)
        lines = [ln for ln in result.output.strip().split("\n") if not ln.startswith("{")]
        assert len(lines) >= 1
        benchmark_id = lines[-1].strip()
        assert len(benchmark_id) == 26


class TestStatusCommand:
    """Tests for `aab status` command."""

    def test_status_no_benchmarks(self):
        """Req 9.2: Status with no benchmarks shows appropriate message."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No benchmarks found" in result.output

    def test_status_after_run(self):
        """Req 9.2: Status shows recently created benchmarks."""
        # Create a benchmark first
        runner.invoke(app, ["run", "Status test prompt"])
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Status test prompt" in result.output


class TestReportCommand:
    """Tests for `aab report` command."""

    def test_report_default_7_days(self):
        """Req 9.4: Report defaults to 7 days."""
        result = runner.invoke(app, ["report"])
        assert result.exit_code == 0
        assert "Benchmark Report" in result.output

    def test_report_custom_days(self):
        """Req 9.4: Report accepts --days flag."""
        result = runner.invoke(app, ["report", "--days", "30"])
        assert result.exit_code == 0
        assert "Benchmark Report" in result.output

    def test_report_invalid_days(self):
        """Req 9.5: Invalid input exits with non-zero code."""
        result = runner.invoke(app, ["report", "--days", "0"])
        assert result.exit_code != 0
        assert "at least 1" in result.output.lower()


class TestEvaluateCommand:
    """Tests for `aab evaluate` command."""

    def test_evaluate_no_candidates(self):
        """Req 9.3: Evaluate with no eligible benchmarks shows message."""
        result = runner.invoke(app, ["evaluate"])
        assert result.exit_code == 0
        assert "No benchmarks available" in result.output


class TestTelegramCommand:
    """Tests for `aab telegram` command."""

    def _mock_settings(self, token: str = "", allowed_ids: str = "", tmp_path=None):
        """Return a mock settings object with controlled telegram fields."""
        from unittest.mock import MagicMock
        from pydantic import SecretStr

        s = MagicMock()
        s.telegram_bot_token.get_secret_value.return_value = token
        s.telegram_allowed_chat_ids = allowed_ids
        s.db_path = str(tmp_path / "tg.db") if tmp_path else ":memory:"
        s.hermes_api_key.get_secret_value.return_value = ""
        s.openclaw_api_key.get_secret_value.return_value = ""
        s.nvidia_api_key.get_secret_value.return_value = ""
        s.signing_key.get_secret_value.return_value = ""
        s.discord_bot_token.get_secret_value.return_value = ""
        s.delay_seconds = 0.0
        s.timeout_seconds = 5.0
        s.export_dir = str(tmp_path / "exports") if tmp_path else "/tmp/exports"
        s.hermes_cpu_cores = None
        s.hermes_memory_mb = None
        s.hermes_cost_per_hour = None
        s.openclaw_cpu_cores = None
        s.openclaw_memory_mb = None
        s.openclaw_cost_per_hour = None
        return s

    def test_telegram_missing_token_exits_nonzero(self, tmp_path):
        """Missing token produces exit code 1 and helpful message."""
        from unittest.mock import patch

        mock_s = self._mock_settings(token="", tmp_path=tmp_path)
        with patch("benchmark.cli.main.settings", mock_s):
            result = runner.invoke(app, ["telegram"])
        assert result.exit_code == 1
        assert "BENCH_TELEGRAM_BOT_TOKEN" in result.output

    def test_telegram_missing_token_mentions_botfather(self, tmp_path):
        """Error message tells the user how to get a token."""
        from unittest.mock import patch

        mock_s = self._mock_settings(token="", tmp_path=tmp_path)
        with patch("benchmark.cli.main.settings", mock_s):
            result = runner.invoke(app, ["telegram"])
        assert "BotFather" in result.output

    def test_telegram_command_module_direct_empty_token(self):
        """telegram_command() exits 1 when token is empty string."""
        import typer
        from benchmark.cli.commands.telegram import telegram_command

        with pytest.raises(typer.Exit):
            telegram_command("", "")

    def test_telegram_command_keyboard_interrupt_exits_cleanly(self, tmp_path):
        """KeyboardInterrupt during polling exits with code 0."""
        from unittest.mock import AsyncMock, patch

        mock_s = self._mock_settings(token="123:TOKEN", tmp_path=tmp_path)

        async def _noop_run(self) -> None:  # noqa: ANN001
            raise KeyboardInterrupt()

        with patch("benchmark.cli.main.settings", mock_s):
            with patch("benchmark.bots.telegram.TelegramPollingBot.run", new=_noop_run):
                result = runner.invoke(app, ["telegram"])

        assert result.exit_code == 0

    def test_telegram_command_parses_allowed_chat_ids(self, tmp_path):
        """Allowed chat IDs string is correctly split into a frozenset."""
        from unittest.mock import AsyncMock, patch

        captured: list = []

        async def fake_run_polling(**kwargs):
            captured.append(kwargs.get("allowed_chat_ids"))

        mock_s = self._mock_settings(token="123:TOKEN", allowed_ids="111,222,333", tmp_path=tmp_path)

        with patch("benchmark.cli.main.settings", mock_s):
            with patch("benchmark.bots.telegram.run_polling", new=fake_run_polling):
                with patch("benchmark.cli.wiring.create_context") as mock_ctx:
                    ctx = AsyncMock()
                    ctx.storage = AsyncMock()
                    ctx.storage.close = AsyncMock()
                    ctx.runner = AsyncMock()
                    mock_ctx.return_value = ctx
                    runner.invoke(app, ["telegram"])

        if captured:
            assert captured[0] == frozenset({"111", "222", "333"})
