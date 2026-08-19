"""Integration tests for provider and cost metrics collection and reporting.

Verifies:
- Cost calculation accuracy (latency-based)
- CPU/memory persisted through SQLite
- Report includes cost analysis section
- Export includes deployment metrics (estimated_infra_cost_usd, cpu_cores, memory_mb)

Requirements: 4.1, 4.2, 4.3, 8.2, 8.3; FR-207, ADR-0006
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

from benchmark.agents.hermes import HermesAdapter
from benchmark.agents.openclaw import OpenClawAdapter
from benchmark.agents.registry import AgentRegistry
from benchmark.evaluation.service import EvaluationService
from benchmark.export.daily import DailyExporter
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    Evaluation,
)
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner, DeploymentResourceConfig
from benchmark.storage.manager import StorageManager

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Mock transport
# ---------------------------------------------------------------------------


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/models" in url:
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})
    if "/chat/completions" in url:
        if ":8001" in url:
            content = "Hermes response for cost test"
        else:
            content = "OpenClaw response for cost test"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "model": "test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )
    return httpx.Response(404, text="Not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_runner_with_costs(
    tmp_path: Path,
    hermes_cost_per_hour: float | None = 1.0,
    openclaw_cost_per_hour: float | None = 2.0,
    hermes_cpu: float | None = 4.0,
    hermes_mem: float | None = 8192.0,
    openclaw_cpu: float | None = 2.0,
    openclaw_mem: float | None = 4096.0,
) -> tuple[StorageManager, BenchmarkRunner, DailyExporter, ReportGenerator, EvaluationService]:
    """Build a runner with deployment resource configs."""
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path=str(db_path))
    await storage.initialize()

    transport = httpx.MockTransport(_mock_handler)
    hermes_http = httpx.AsyncClient(transport=transport)
    openclaw_http = httpx.AsyncClient(transport=transport)

    hermes = HermesAdapter(endpoint="http://localhost:8001", api_key="key-h", client=hermes_http)
    openclaw = OpenClawAdapter(
        endpoint="http://localhost:8002", api_key="key-o", client=openclaw_http
    )

    registry = AgentRegistry()
    registry.register(hermes, DeploymentType.VIRTUAL_MACHINE, "http://localhost:8001")
    registry.register(openclaw, DeploymentType.MANAGED_CONTAINER, "http://localhost:8002")

    runner_config = RunnerConfig(
        execution_order=[
            ("hermes", DeploymentType.VIRTUAL_MACHINE),
            ("openclaw", DeploymentType.MANAGED_CONTAINER),
        ],
        delay_between_seconds=0.0,
        timeout_seconds=10.0,
    )

    deployment_configs: dict[str, DeploymentResourceConfig] = {}
    if hermes_cost_per_hour is not None or hermes_cpu is not None or hermes_mem is not None:
        deployment_configs["hermes"] = DeploymentResourceConfig(
            cpu_cores=hermes_cpu,
            memory_mb=hermes_mem,
            cost_per_hour=hermes_cost_per_hour,
        )
    if openclaw_cost_per_hour is not None or openclaw_cpu is not None or openclaw_mem is not None:
        deployment_configs["openclaw"] = DeploymentResourceConfig(
            cpu_cores=openclaw_cpu,
            memory_mb=openclaw_mem,
            cost_per_hour=openclaw_cost_per_hour,
        )

    runner = BenchmarkRunner(
        registry=registry,
        storage=storage,
        config=runner_config,
        deployment_configs=deployment_configs,
    )

    exporter = DailyExporter(storage=storage, export_dir=tmp_path / "exports")
    report_generator = ReportGenerator(storage=storage)
    evaluation_service = EvaluationService(storage=storage)

    return storage, runner, exporter, report_generator, evaluation_service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cost_calculation_accuracy(tmp_path: Path) -> None:
    """Verify per-execution infra cost = (latency_ms / 3_600_000) * cost_per_hour."""
    storage, runner, _, _, _ = await _build_runner_with_costs(
        tmp_path, hermes_cost_per_hour=3.6, openclaw_cost_per_hour=7.2
    )
    try:
        benchmark = Benchmark(source="cli", prompt="Cost calculation test")
        await storage.save_benchmark(benchmark)
        status = await runner.run(benchmark)

        assert status == BenchmarkStatus.COMPLETED

        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 2

        for ex in executions:
            assert ex.deployment.estimated_infra_cost_usd is not None
            latency_ms = ex.deployment.total_latency_ms
            if ex.agent_name == "hermes":
                expected_cost = (latency_ms / 3_600_000) * 3.6
            else:
                expected_cost = (latency_ms / 3_600_000) * 7.2
            assert abs(ex.deployment.estimated_infra_cost_usd - expected_cost) < 1e-9
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cpu_memory_persisted_through_sqlite(tmp_path: Path) -> None:
    """Verify cpu_cores and memory_mb are persisted and retrieved from SQLite."""
    storage, runner, _, _, _ = await _build_runner_with_costs(
        tmp_path,
        hermes_cpu=4.0,
        hermes_mem=8192.0,
        openclaw_cpu=2.0,
        openclaw_mem=4096.0,
    )
    try:
        benchmark = Benchmark(source="cli", prompt="Resource metrics test")
        await storage.save_benchmark(benchmark)
        await runner.run(benchmark)

        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 2

        hermes_ex = executions[0]
        assert hermes_ex.agent_name == "hermes"
        assert hermes_ex.deployment.cpu_cores == 4.0
        assert hermes_ex.deployment.memory_mb == 8192

        openclaw_ex = executions[1]
        assert openclaw_ex.agent_name == "openclaw"
        assert openclaw_ex.deployment.cpu_cores == 2.0
        assert openclaw_ex.deployment.memory_mb == 4096
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_includes_cost_analysis_section(tmp_path: Path) -> None:
    """Verify the report includes a Cost Analysis section with infra costs."""
    storage, runner, _, report_gen, eval_service = await _build_runner_with_costs(tmp_path)
    try:
        # Need at least 5 benchmarks with evaluations for recommendations
        for i in range(6):
            benchmark = Benchmark(source="cli", prompt=f"Cost report test {i}", tags=["infra-test"])
            await storage.save_benchmark(benchmark)
            await runner.run(benchmark)

            evaluation = Evaluation(
                benchmark_id=benchmark.id,
                rating=4,
                preferred_agent="hermes",
                preferred_deployment=DeploymentType.VIRTUAL_MACHINE,
            )
            await eval_service.submit(evaluation)

        today = datetime.now(UTC).date().isoformat()
        report = await report_gen.generate(today, today)

        # Cost Analysis section present
        assert "## Cost Analysis" in report
        assert "Avg Infra Cost/Exec" in report

        # Provider info in recommendations
        assert "## Recommendations" in report
        assert "Provider" in report
        assert "vm" in report  # Provider column shows "vm"
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_cost_analysis_no_data(tmp_path: Path) -> None:
    """Verify report shows appropriate message when no cost data is available."""
    storage, runner, _, report_gen, eval_service = await _build_runner_with_costs(
        tmp_path,
        hermes_cost_per_hour=None,
        openclaw_cost_per_hour=None,
        hermes_cpu=None,
        hermes_mem=None,
        openclaw_cpu=None,
        openclaw_mem=None,
    )
    try:
        for i in range(6):
            benchmark = Benchmark(source="cli", prompt=f"No cost test {i}", tags=["no-cost"])
            await storage.save_benchmark(benchmark)
            await runner.run(benchmark)

            evaluation = Evaluation(
                benchmark_id=benchmark.id,
                rating=3,
                preferred_agent="hermes",
                preferred_deployment=DeploymentType.VIRTUAL_MACHINE,
            )
            await eval_service.submit(evaluation)

        today = datetime.now(UTC).date().isoformat()
        report = await report_gen.generate(today, today)

        assert "## Cost Analysis" in report
        assert "No infrastructure cost data available" in report
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_includes_deployment_metrics(tmp_path: Path) -> None:
    """Verify export CSV and JSONL include cpu_cores, memory_mb, estimated_infra_cost_usd."""
    storage, runner, exporter, _, _ = await _build_runner_with_costs(tmp_path)
    try:
        benchmark = Benchmark(source="cli", prompt="Export metrics test")
        await storage.save_benchmark(benchmark)
        await runner.run(benchmark)

        today = datetime.now(UTC).date().isoformat()
        manifest = await exporter.export_day(today)

        # Check JSONL export
        jsonl_path = next(f for f in manifest.files if f.endswith(".jsonl"))
        with open(jsonl_path) as f:
            lines = f.readlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        execs = record["executions"]
        assert len(execs) == 2

        for ex_data in execs:
            deployment = ex_data["deployment"]
            assert "cpu_cores" in deployment
            assert "memory_mb" in deployment
            assert "estimated_infra_cost_usd" in deployment
            assert deployment["cpu_cores"] is not None
            assert deployment["memory_mb"] is not None
            assert deployment["estimated_infra_cost_usd"] is not None

        # Check CSV export
        exec_csv_path = next(f for f in manifest.files if "executions" in f and f.endswith(".csv"))
        with open(exec_csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        for row in rows:
            assert "cpu_cores" in row
            assert "memory_mb" in row
            assert "estimated_infra_cost_usd" in row
            assert row["cpu_cores"] != ""
            assert row["memory_mb"] != ""
            assert row["estimated_infra_cost_usd"] != ""
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_cost_config_means_null_infra_cost(tmp_path: Path) -> None:
    """Without cost_per_hour config, estimated_infra_cost_usd is None."""
    storage, runner, _, _, _ = await _build_runner_with_costs(
        tmp_path,
        hermes_cost_per_hour=None,
        openclaw_cost_per_hour=None,
        hermes_cpu=None,
        hermes_mem=None,
        openclaw_cpu=None,
        openclaw_mem=None,
    )
    try:
        benchmark = Benchmark(source="cli", prompt="No config test")
        await storage.save_benchmark(benchmark)
        await runner.run(benchmark)

        executions = await storage.get_executions(benchmark.id)
        for ex in executions:
            assert ex.deployment.estimated_infra_cost_usd is None
            assert ex.deployment.cpu_cores is None
            assert ex.deployment.memory_mb is None
    finally:
        await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_response_content_preserved_with_cost_metrics(tmp_path: Path) -> None:
    """Cost metrics don't interfere with actual response content or errors."""
    storage, runner, _, _, _ = await _build_runner_with_costs(tmp_path)
    try:
        benchmark = Benchmark(source="cli", prompt="Content preservation test")
        await storage.save_benchmark(benchmark)
        await runner.run(benchmark)

        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 2

        # Response content is preserved
        assert executions[0].result.raw_response == "Hermes response for cost test"
        assert executions[1].result.raw_response == "OpenClaw response for cost test"

        # Cost is also present
        assert executions[0].deployment.estimated_infra_cost_usd is not None
        assert executions[1].deployment.estimated_infra_cost_usd is not None

        # LLM metrics are also preserved
        assert executions[0].llm is not None
        assert executions[0].llm.total_tokens == 30
    finally:
        await storage.close()
