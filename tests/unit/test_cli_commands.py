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
