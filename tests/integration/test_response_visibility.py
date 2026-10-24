"""Integration coverage for response, error, export, CLI, and report visibility."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from benchmark.cli.main import app
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
from benchmark.report.generator import ReportGenerator
from benchmark.storage.manager import StorageManager

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _execution(
    benchmark_id: str,
    agent_name: str,
    deployment: DeploymentType,
    *,
    response: str,
    errors: list[str] | None = None,
    success: bool = True,
    latency: float = 1234.5,
    cost: float = 0.123,
) -> Execution:
    return Execution(
        benchmark_id=benchmark_id,
        agent_name=agent_name,
        agent_version="integration-1",
        deployment=DeploymentMetrics(
            provider="integration",
            deployment_type=deployment,
            cpu_cores=2.5,
            memory_mb=1024,
            cold_start_ms=17.25,
            total_latency_ms=latency,
            network_latency_ms=8.5,
        ),
        llm=LLMMetrics(
            model="integration-model",
            prompt_tokens=11,
            completion_tokens=22,
            total_tokens=33,
            api_latency_ms=45.5,
            estimated_cost_usd=cost,
        ),
        result=ExecutionResult(
            raw_response=response,
            errors=errors or [],
            logs=["execution started"],
        ),
        started_at=datetime(2024, 6, 15, 10, 0, tzinfo=UTC),
        completed_at=datetime(2024, 6, 15, 10, 0, 1, tzinfo=UTC),
        success=success,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_storage_and_daily_export_preserve_response_errors_and_metrics(
    tmp_path: Path,
) -> None:
    """SQLite, JSONL, and CSV expose exact result payloads and metrics."""
    date = "2024-06-15"
    benchmark = Benchmark(
        id="01HVISIBILITY00000000000001",
        source="cli",
        prompt="Compare the outputs",
        status=BenchmarkStatus.PARTIALLY_FAILED,
        tags=["visibility"],
        created_at=datetime(2024, 6, 15, 9, 0, tzinfo=UTC),
    )
    exact_response = "line one\n  line two with trailing spaces  "
    errors = ["unsupported_modality:video", "provider_warning"]
    failed = _execution(
        benchmark.id,
        "failed-agent",
        DeploymentType.LOCAL_DOCKER,
        response=exact_response,
        errors=errors,
        success=False,
        latency=9876.5,
        cost=0.987,
    )

    storage = StorageManager(tmp_path / "visibility.db")
    await storage.initialize()
    await storage.save_benchmark(benchmark)
    await storage.save_execution(failed)
    restored = (await storage.get_executions(benchmark.id))[0]
    assert restored.model_dump(mode="python") == failed.model_dump(mode="python")

    exporter = DailyExporter(storage, tmp_path / "exports")
    await exporter.export_day(date)
    date_dir = tmp_path / "exports" / date
    record = json.loads((date_dir / f"benchmarks_{date}.jsonl").read_text())
    exported = record["executions"][0]
    assert exported["result"]["raw_response"] == exact_response
    assert exported["result"]["errors"] == errors
    assert exported["success"] is False
    assert exported["deployment"]["total_latency_ms"] == 9876.5
    assert exported["llm"]["estimated_cost_usd"] == 0.987

    with (date_dir / f"executions_{date}.csv").open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["raw_response"] == exact_response
    assert json.loads(row["errors"]) == errors
    assert row["success"] == "False"
    assert float(row["total_latency_ms"]) == 9876.5
    assert float(row["estimated_cost_usd"]) == 0.987
    await storage.close()


@pytest.mark.integration
def test_evaluate_displays_full_responses_and_execution_errors(tmp_path: Path, monkeypatch) -> None:
    """The interactive evaluator prints every response and each error clearly."""
    import asyncio

    db_path = tmp_path / "evaluate.db"

    async def seed() -> None:
        storage = StorageManager(db_path)
        await storage.initialize()
        benchmark = Benchmark(
            id="01HVISIBILITY00000000000002",
            source="cli",
            prompt="Evaluate these responses",
            status=BenchmarkStatus.PARTIALLY_FAILED,
        )
        await storage.save_benchmark(benchmark)
        await storage.save_execution(
            _execution(
                benchmark.id,
                "agent-one",
                DeploymentType.LOCAL_DOCKER,
                response="complete response\nwith all content",
            )
        )
        await storage.save_execution(
            _execution(
                benchmark.id,
                "agent-two",
                DeploymentType.VIRTUAL_MACHINE,
                response="partial response\nthat remains visible  ",
                errors=["unsupported_modality:audio", "provider_warning"],
                success=False,
            )
        )
        await storage.close()

    asyncio.run(seed())
    monkeypatch.setenv("BENCH_DB_PATH", str(db_path))
    result = runner.invoke(
        app,
        ["evaluate"],
        input="1\n4\nagent-one\nUseful comparison\n",
    )

    assert result.exit_code == 0, result.output
    assert "complete response\nwith all content" in result.output
    assert "partial response\nthat remains visible  " in result.output
    assert "Execution errors:" in result.output
    assert "unsupported_modality:audio" in result.output
    assert "provider_warning" in result.output


@pytest.mark.integration
@pytest.mark.asyncio
async def test_report_exposes_failures_and_preserves_metrics(tmp_path: Path) -> None:
    """Reports show failed executions while retaining existing metric output."""
    storage = StorageManager(tmp_path / "report.db")
    await storage.initialize()
    created_at = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)

    for index in range(5):
        benchmark_id = f"01HVISIBILITY{index:014d}"
        benchmark = Benchmark(
            id=benchmark_id,
            source="cli",
            prompt="Report response visibility",
            status=BenchmarkStatus.PARTIALLY_FAILED,
            tags=["visibility"],
            created_at=created_at,
        )
        await storage.save_benchmark(benchmark)
        await storage.save_execution(
            _execution(
                benchmark_id,
                "good-agent",
                DeploymentType.LOCAL_DOCKER,
                response=f"good response {index}",
                latency=1234.5,
                cost=0.123,
            )
        )
        await storage.save_execution(
            _execution(
                benchmark_id,
                "modality-agent",
                DeploymentType.VIRTUAL_MACHINE,
                response="",
                errors=["unsupported_modality:image"],
                success=False,
                latency=9876.5,
                cost=0.987,
            )
        )
        await storage.save_evaluation(
            Evaluation(
                benchmark_id=benchmark_id,
                rating=4,
                preferred_agent="good-agent",
                preferred_deployment=DeploymentType.LOCAL_DOCKER,
                evaluated_at=created_at,
            )
        )

    report = await ReportGenerator(storage).generate("2024-06-01", "2024-06-30")
    await storage.close()

    assert "## Execution Errors" in report
    assert "unsupported_modality:image" in report
    assert "| good-agent/local_docker | 100.0% | $0.123000/req | 1234.5ms | 0 |" in report
    assert "| modality-agent/vm | 0.0% | $0.987000/req | 9876.5ms | 5 |" in report
    recommendations = report.split("## Recommendations", 1)[1]
    assert "good-agent/local_docker" in recommendations
    assert "modality-agent/vm" not in recommendations
