"""Unit tests for DailyExporter covering normal export, empty date, idempotency, manifest accuracy."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benchmark.export.daily import DailyExporter
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Evaluation,
    Execution,
    ExecutionResult,
    LLMMetrics,
)
from benchmark.storage.manager import StorageManager


@pytest.fixture
async def storage(tmp_path: Path) -> StorageManager:
    """Create a temporary StorageManager with initialized schema."""
    db_path = tmp_path / "test.db"
    sm = StorageManager(db_path)
    await sm.initialize()
    yield sm
    await sm.close()


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    """Provide a temporary export directory."""
    return tmp_path / "exports"


def _make_benchmark(date_str: str = "2024-06-15", idx: int = 0) -> Benchmark:
    """Create a test benchmark with created_at on the given date."""
    return Benchmark(
        source="cli",
        prompt=f"Test prompt {idx}",
        status=BenchmarkStatus.COMPLETED,
        created_at=datetime.fromisoformat(f"{date_str}T10:{idx:02d}:00+00:00"),
        completed_at=datetime.fromisoformat(f"{date_str}T10:{idx:02d}:30+00:00"),
    )


def _make_execution(benchmark_id: str) -> Execution:
    """Create a test execution linked to a benchmark."""
    now = datetime.now(UTC)
    return Execution(
        benchmark_id=benchmark_id,
        agent_name="hermes",
        agent_version="1.0.0",
        deployment=DeploymentMetrics(
            provider="local",
            deployment_type=DeploymentType.LOCAL_DOCKER,
            total_latency_ms=150.5,
        ),
        llm=LLMMetrics(model="gpt-4", prompt_tokens=100, completion_tokens=50),
        result=ExecutionResult(raw_response="Hello world"),
        started_at=now,
        completed_at=now,
        success=True,
    )


def _make_evaluation(benchmark_id: str) -> Evaluation:
    """Create a test evaluation linked to a benchmark."""
    return Evaluation(
        benchmark_id=benchmark_id,
        rating=4,
        preferred_agent="hermes",
        notes="Good response",
    )


class TestDailyExporterNormal:
    """Test normal export with benchmarks, executions, and evaluations."""

    async def test_export_produces_all_files(self, storage: StorageManager, export_dir: Path):
        """Export produces JSONL + 3 CSV files."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)
        await storage.save_execution(_make_execution(b.id))
        await storage.save_evaluation(_make_evaluation(b.id))

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        manifest = await exporter.export_day(date)

        assert len(manifest.files) == 4
        for f in manifest.files:
            assert Path(f).exists()

    async def test_jsonl_structure(self, storage: StorageManager, export_dir: Path):
        """JSONL file has one JSON object per line with correct structure."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)
        await storage.save_execution(_make_execution(b.id))
        await storage.save_evaluation(_make_evaluation(b.id))

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        await exporter.export_day(date)

        jsonl_path = export_dir / date / f"benchmarks_{date}.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert "benchmark" in record
        assert "executions" in record
        assert "evaluation" in record
        assert isinstance(record["executions"], list)
        assert len(record["executions"]) == 1
        assert record["evaluation"] is not None

    async def test_csv_benchmarks_columns(self, storage: StorageManager, export_dir: Path):
        """Benchmarks CSV has correct headers and data."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        await exporter.export_day(date)

        csv_path = export_dir / date / f"benchmarks_{date}.csv"
        with open(csv_path) as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == ["id", "source", "prompt", "status", "created_at", "completed_at"]
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0][0] == b.id
            assert rows[0][1] == "cli"

    async def test_csv_executions_columns(self, storage: StorageManager, export_dir: Path):
        """Executions CSV has correct headers and data."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)
        ex = _make_execution(b.id)
        await storage.save_execution(ex)

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        await exporter.export_day(date)

        csv_path = export_dir / date / f"executions_{date}.csv"
        with open(csv_path) as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == [
                "id",
                "benchmark_id",
                "agent_name",
                "deployment_provider",
                "deployment_type",
                "cpu_cores",
                "memory_mb",
                "cold_start_ms",
                "total_latency_ms",
                "network_latency_ms",
                "estimated_infra_cost_usd",
                "llm_model",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "api_latency_ms",
                "estimated_cost_usd",
                "raw_response",
                "errors",
                "logs",
                "tool_calls",
                "browser_actions",
                "success",
            ]
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0][1] == b.id
            assert rows[0][2] == "hermes"
            assert rows[0][3] == "local"
            assert rows[0][4] == "local_docker"
            assert rows[0][18] == "[]"
            assert rows[0][22] == "True"

    async def test_csv_evaluations_columns(self, storage: StorageManager, export_dir: Path):
        """Evaluations CSV has correct headers and data."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)
        await storage.save_evaluation(_make_evaluation(b.id))

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        await exporter.export_day(date)

        csv_path = export_dir / date / f"evaluations_{date}.csv"
        with open(csv_path) as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == ["id", "benchmark_id", "rating", "preferred_agent", "notes"]
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0][1] == b.id
            assert rows[0][2] == "4"


class TestDailyExporterEmptyDate:
    """Test export for a date with no benchmarks (Req 7.6)."""

    async def test_empty_jsonl_zero_bytes(self, storage: StorageManager, export_dir: Path):
        """JSONL file is empty (zero bytes) for a date with no benchmarks."""
        date = "2024-01-01"
        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        await exporter.export_day(date)

        jsonl_path = export_dir / date / f"benchmarks_{date}.jsonl"
        assert jsonl_path.exists()
        assert jsonl_path.stat().st_size == 0

    async def test_empty_csv_headers_only(self, storage: StorageManager, export_dir: Path):
        """CSV files contain only headers for a date with no benchmarks."""
        date = "2024-01-01"
        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        await exporter.export_day(date)

        for name in ["benchmarks", "executions", "evaluations"]:
            csv_path = export_dir / date / f"{name}_{date}.csv"
            assert csv_path.exists()
            with open(csv_path) as f:
                reader = csv.reader(f)
                headers = next(reader)
                assert len(headers) > 0  # Has headers
                rows = list(reader)
                assert len(rows) == 0  # No data rows

    async def test_empty_manifest_zero_counts(self, storage: StorageManager, export_dir: Path):
        """Manifest has zero counts for empty date."""
        date = "2024-01-01"
        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        manifest = await exporter.export_day(date)

        assert manifest.benchmark_count == 0
        assert manifest.execution_count == 0
        assert manifest.evaluation_count == 0


class TestDailyExporterIdempotency:
    """Test idempotent overwrite behavior (Req 7.4)."""

    async def test_rerun_produces_identical_output(self, storage: StorageManager, export_dir: Path):
        """Re-running export for same date produces identical files."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)
        await storage.save_execution(_make_execution(b.id))
        await storage.save_evaluation(_make_evaluation(b.id))

        exporter = DailyExporter(storage=storage, export_dir=export_dir)

        # First export
        await exporter.export_day(date)
        first_contents = {}
        date_dir = export_dir / date
        for f in date_dir.iterdir():
            first_contents[f.name] = f.read_bytes()

        # Second export (overwrite)
        await exporter.export_day(date)
        for f in date_dir.iterdir():
            assert f.read_bytes() == first_contents[f.name], f"File {f.name} differs on re-export"


class TestDailyExporterManifest:
    """Test manifest accuracy (Req 7.5)."""

    async def test_manifest_counts_match_data(self, storage: StorageManager, export_dir: Path):
        """Manifest counts match actual data written."""
        date = "2024-06-15"
        # Create 2 benchmarks, 3 executions, 1 evaluation
        b1 = _make_benchmark(date, idx=0)
        b2 = _make_benchmark(date, idx=1)
        await storage.save_benchmark(b1)
        await storage.save_benchmark(b2)
        await storage.save_execution(_make_execution(b1.id))
        await storage.save_execution(_make_execution(b1.id))
        await storage.save_execution(_make_execution(b2.id))
        await storage.save_evaluation(_make_evaluation(b1.id))

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        manifest = await exporter.export_day(date)

        assert manifest.benchmark_count == 2
        assert manifest.execution_count == 3
        assert manifest.evaluation_count == 1
        assert manifest.date == date
        assert manifest.exported_at is not None
        assert len(manifest.files) == 4

    async def test_manifest_file_paths_exist(self, storage: StorageManager, export_dir: Path):
        """All file paths in manifest exist on disk."""
        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)

        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        manifest = await exporter.export_day(date)

        for file_path in manifest.files:
            assert Path(file_path).exists()

    async def test_manifest_file_naming_convention(self, storage: StorageManager, export_dir: Path):
        """Files follow {type}_{date}.{ext} naming convention."""
        date = "2024-06-15"
        exporter = DailyExporter(storage=storage, export_dir=export_dir)
        manifest = await exporter.export_day(date)

        filenames = [Path(f).name for f in manifest.files]
        assert f"benchmarks_{date}.jsonl" in filenames
        assert f"benchmarks_{date}.csv" in filenames
        assert f"executions_{date}.csv" in filenames
        assert f"evaluations_{date}.csv" in filenames


class TestDailyExporterErrorHandling:
    """Test export error handling — no partial files on failure (Req 7.7)."""

    async def test_storage_read_error_raises_export_error(
        self, storage: StorageManager, export_dir: Path
    ):
        """Storage read error raises ExportError and leaves no partial files."""
        from unittest.mock import AsyncMock, patch

        from benchmark.export.daily import ExportError

        date = "2024-06-15"
        exporter = DailyExporter(storage=storage, export_dir=export_dir)

        with patch.object(storage, "get_benchmarks_for_date", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = RuntimeError("database is locked")
            with pytest.raises(ExportError, match="Storage read error"):
                await exporter.export_day(date)

        # No partial files should remain
        date_dir = export_dir / date
        assert not date_dir.exists()

    async def test_write_error_mid_export_cleans_up(
        self, storage: StorageManager, export_dir: Path
    ):
        """File write error mid-export raises ExportError and removes partial files."""
        from unittest.mock import patch

        from benchmark.export.daily import ExportError

        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)
        await storage.save_execution(_make_execution(b.id))

        exporter = DailyExporter(storage=storage, export_dir=export_dir)

        # Simulate a write failure on the second CSV (executions)
        original_write_csv = exporter._write_csv
        call_count = 0

        def failing_write_csv(path, items, columns, row_fn):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # Fail on second CSV write
                # Write a partial file first to simulate real failure
                path.write_text("partial")
                raise OSError("disk full")
            return original_write_csv(path, items, columns, row_fn)

        with (
            patch.object(exporter, "_write_csv", side_effect=failing_write_csv),
            pytest.raises(ExportError, match="File write error"),
        ):
            await exporter.export_day(date)

        # Entire date directory should be cleaned up
        date_dir = export_dir / date
        assert not date_dir.exists()

    async def test_export_error_contains_reason(self, storage: StorageManager, export_dir: Path):
        """ExportError message includes the failure reason."""
        from unittest.mock import AsyncMock, patch

        from benchmark.export.daily import ExportError

        date = "2024-06-15"
        exporter = DailyExporter(storage=storage, export_dir=export_dir)

        with patch.object(storage, "get_benchmarks_for_date", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = ConnectionError("connection reset")
            with pytest.raises(ExportError) as exc_info:
                await exporter.export_day(date)

        assert "connection reset" in str(exc_info.value)

    async def test_execution_read_error_cleans_up(self, storage: StorageManager, export_dir: Path):
        """Error when reading executions also triggers cleanup."""
        from unittest.mock import AsyncMock, patch

        from benchmark.export.daily import ExportError

        date = "2024-06-15"
        b = _make_benchmark(date)
        await storage.save_benchmark(b)

        exporter = DailyExporter(storage=storage, export_dir=export_dir)

        with patch.object(storage, "get_executions", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("corrupted database")
            with pytest.raises(ExportError, match="Storage read error"):
                await exporter.export_day(date)

        date_dir = export_dir / date
        assert not date_dir.exists()
