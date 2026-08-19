"""Property tests for daily export (Task 8.3).

Property 9: Export Idempotency — export the same date twice, verify identical output.
Property 10: Export Manifest Accuracy — verify manifest counts match actual data.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.export.daily import DailyExporter
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Execution,
    ExecutionResult,
    LLMMetrics,
)
from benchmark.storage.manager import StorageManager

# --- Strategies ---

_agent_names = st.sampled_from(["hermes", "openclaw", "gpt-agent", "claude-agent"])
_sources = st.sampled_from(["telegram", "discord", "cli", "api"])


def _make_execution(benchmark_id: str, agent_name: str) -> Execution:
    """Create a minimal valid Execution for a given benchmark."""
    now = datetime.now(UTC)
    return Execution(
        benchmark_id=benchmark_id,
        agent_name=agent_name,
        agent_version="1.0.0",
        deployment=DeploymentMetrics(
            provider="docker",
            deployment_type=DeploymentType.LOCAL_DOCKER,
            total_latency_ms=100.0,
        ),
        llm=LLMMetrics(model="gpt-4", prompt_tokens=10, completion_tokens=20, total_tokens=30),
        result=ExecutionResult(raw_response="test response"),
        started_at=now,
        completed_at=now,
        success=True,
    )


@st.composite
def benchmarks_with_executions(draw: st.DrawFn) -> list[tuple[Benchmark, list[Execution]]]:
    """Generate 1-5 benchmarks each with 1-3 executions."""
    num_benchmarks = draw(st.integers(min_value=1, max_value=5))
    results: list[tuple[Benchmark, list[Execution]]] = []
    for _ in range(num_benchmarks):
        source = draw(_sources)
        benchmark = Benchmark(
            source=source,
            prompt="Test benchmark prompt for export",
            status=BenchmarkStatus.COMPLETED,
            created_at=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        )
        num_executions = draw(st.integers(min_value=1, max_value=3))
        executions = []
        for _ in range(num_executions):
            agent = draw(_agent_names)
            executions.append(_make_execution(benchmark.id, agent))
        results.append((benchmark, executions))
    return results


async def _setup_storage(base_dir: Path) -> StorageManager:
    """Create and initialize a temporary StorageManager."""
    db_path = base_dir / "test.db"
    storage = StorageManager(db_path)
    await storage.initialize()
    return storage


# --- Property 9: Export Idempotency ---


@settings(max_examples=10)
@given(source=_sources)
@pytest.mark.property
async def test_export_idempotency(source: str) -> None:
    """Exporting the same date twice produces identical file contents."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            # Create a benchmark for the target date
            benchmark = Benchmark(
                source=source,
                prompt="Idempotency test prompt",
                status=BenchmarkStatus.COMPLETED,
                created_at=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            )
            await storage.save_benchmark(benchmark)
            execution = _make_execution(benchmark.id, "hermes")
            await storage.save_execution(execution)

            target_date = "2024-06-15"

            # First export
            export_dir_1 = tmp_dir / "export1"
            exporter1 = DailyExporter(storage, export_dir=export_dir_1)
            await exporter1.export_day(target_date)

            # Second export
            export_dir_2 = tmp_dir / "export2"
            exporter2 = DailyExporter(storage, export_dir=export_dir_2)
            await exporter2.export_day(target_date)

            # Compare all files byte-for-byte
            files_1 = sorted((export_dir_1 / target_date).iterdir())
            files_2 = sorted((export_dir_2 / target_date).iterdir())

            assert len(files_1) == len(files_2), "Export produced different number of files"
            for f1, f2 in zip(files_1, files_2, strict=True):
                assert f1.name == f2.name, f"File names differ: {f1.name} vs {f2.name}"
                assert f1.read_bytes() == f2.read_bytes(), f"File contents differ for {f1.name}"
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Property 10: Export Manifest Accuracy ---


@settings(max_examples=10)
@given(data=benchmarks_with_executions())
@pytest.mark.property
async def test_export_manifest_accuracy(
    data: list[tuple[Benchmark, list[Execution]]],
) -> None:
    """Manifest benchmark_count and execution_count match actual persisted data."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            expected_benchmark_count = len(data)
            expected_execution_count = sum(len(execs) for _, execs in data)

            for benchmark, executions in data:
                await storage.save_benchmark(benchmark)
                for execution in executions:
                    await storage.save_execution(execution)

            target_date = "2024-06-15"
            export_dir = tmp_dir / "export"
            exporter = DailyExporter(storage, export_dir=export_dir)
            manifest = await exporter.export_day(target_date)

            assert manifest.benchmark_count == expected_benchmark_count
            assert manifest.execution_count == expected_execution_count
            assert manifest.date == target_date
            assert len(manifest.files) > 0
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
