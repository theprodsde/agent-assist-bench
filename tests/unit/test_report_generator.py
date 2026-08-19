"""Tests for ReportGenerator.

Covers report content, tie-breaking logic, and sample size warnings
using pre-seeded data in a temporary SQLite database.
"""

from datetime import UTC, datetime

import pytest

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


@pytest.fixture
async def storage(tmp_path):
    """Create a StorageManager with a temporary database."""
    db_path = tmp_path / "test_report.db"
    manager = StorageManager(db_path)
    await manager.initialize()
    yield manager
    await manager.close()


def _make_benchmark(
    bench_id: str,
    tags: list[str],
    created_at: datetime | None = None,
) -> Benchmark:
    return Benchmark(
        id=bench_id,
        source="cli",
        prompt="Test prompt",
        status=BenchmarkStatus.COMPLETED,
        created_at=created_at or datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        tags=tags,
    )


def _make_execution(
    exec_id: str,
    benchmark_id: str,
    agent_name: str,
    deployment_type: DeploymentType,
    total_latency_ms: float = 2000.0,
    estimated_cost_usd: float | None = 0.01,
) -> Execution:
    llm = (
        LLMMetrics(model="gpt-4", estimated_cost_usd=estimated_cost_usd)
        if estimated_cost_usd is not None
        else None
    )
    return Execution(
        id=exec_id,
        benchmark_id=benchmark_id,
        agent_name=agent_name,
        agent_version="1.0.0",
        deployment=DeploymentMetrics(
            provider="local",
            deployment_type=deployment_type,
            total_latency_ms=total_latency_ms,
        ),
        llm=llm,
        result=ExecutionResult(raw_response="response"),
        started_at=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        completed_at=datetime(2024, 6, 15, 12, 0, 2, tzinfo=UTC),
        success=True,
    )


def _make_evaluation(
    eval_id: str,
    benchmark_id: str,
    preferred_agent: str | None = None,
    preferred_deployment: DeploymentType | None = None,
) -> Evaluation:
    return Evaluation(
        id=eval_id,
        benchmark_id=benchmark_id,
        rating=4,
        preferred_agent=preferred_agent,
        preferred_deployment=preferred_deployment,
        evaluated_at=datetime(2024, 6, 15, 14, 0, 0, tzinfo=UTC),
    )


async def _seed_data(storage: StorageManager, count: int = 6) -> None:
    """Seed benchmarks with evaluations for the 'coding' category.

    Creates `count` benchmarks each with 2 executions (hermes/local_docker
    and openclaw/vm). Evaluations alternate preferring hermes and openclaw.
    """
    for i in range(count):
        bench_id = f"01HTEST{i:020d}"
        bm = _make_benchmark(bench_id, tags=["coding"])
        await storage.save_benchmark(bm)

        exec1_id = f"01HEXEC{i:020d}A"
        exec2_id = f"01HEXEC{i:020d}B"

        await storage.save_execution(
            _make_execution(
                exec1_id,
                bench_id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
                total_latency_ms=2000.0,
                estimated_cost_usd=0.004,
            )
        )
        await storage.save_execution(
            _make_execution(
                exec2_id,
                bench_id,
                "openclaw",
                DeploymentType.VIRTUAL_MACHINE,
                total_latency_ms=3000.0,
                estimated_cost_usd=0.008,
            )
        )

        # Alternate preference: first 4 prefer hermes, last 2 prefer openclaw
        if i < 4:
            pref_agent = "hermes"
            pref_deploy = DeploymentType.LOCAL_DOCKER
        else:
            pref_agent = "openclaw"
            pref_deploy = DeploymentType.VIRTUAL_MACHINE

        eval_id = f"01HEVAL{i:020d}"
        await storage.save_evaluation(_make_evaluation(eval_id, bench_id, pref_agent, pref_deploy))


class TestReportGenerator:
    """Tests for the ReportGenerator class."""

    async def test_basic_report_structure(self, storage):
        """Report contains header, category table, and recommendations."""
        await _seed_data(storage)
        gen = ReportGenerator(storage)

        report = await gen.generate("2024-06-01", "2024-06-30")

        assert "# Benchmark Report: 2024-06-01 to 2024-06-30" in report
        assert "6 Benchmarks Evaluated" in report
        assert "## coding" in report
        assert "## Recommendations" in report

    async def test_win_rate_calculation(self, storage):
        """Win rates are correctly calculated and rounded to 2dp."""
        await _seed_data(storage)
        gen = ReportGenerator(storage)

        report = await gen.generate("2024-06-01", "2024-06-30")

        # hermes/local_docker wins 4 out of 6 = 66.67%
        assert "66.67%" in report
        # openclaw/vm wins 2 out of 6 = 33.33%
        assert "33.33%" in report

    async def test_average_cost_calculation(self, storage):
        """Average costs are correctly calculated."""
        await _seed_data(storage)
        gen = ReportGenerator(storage)

        report = await gen.generate("2024-06-01", "2024-06-30")

        # hermes cost is always $0.004
        assert "$0.0/req" in report or "$0.004/req" in report
        # Let's check exact: 0.004 average rounds to 0.0 at 2dp
        # Actually 0.004 rounds to 0.0 at 2dp. Let me verify...
        # round(0.004, 2) = 0.0 — that's correct
        assert "$0.0/req" in report

    async def test_average_latency_calculation(self, storage):
        """Average latencies are correctly calculated."""
        await _seed_data(storage)
        gen = ReportGenerator(storage)

        report = await gen.generate("2024-06-01", "2024-06-30")

        assert "2000.0ms" in report
        assert "3000.0ms" in report

    async def test_recommendation_highest_win_rate(self, storage):
        """Recommendation picks the agent with highest win rate."""
        await _seed_data(storage)
        gen = ReportGenerator(storage)

        report = await gen.generate("2024-06-01", "2024-06-30")

        # Recommendations section should recommend hermes (66.67% > 33.33%)
        lines = report.split("\n")
        rec_start = next(i for i, line in enumerate(lines) if line.startswith("## Recommendations"))
        rec_section = "\n".join(lines[rec_start:])
        assert "hermes/local_docker" in rec_section

    async def test_recommendation_tie_break_by_latency(self, storage):
        """When win rates tie, recommendation picks lowest latency."""
        # Create data where both agents have 50% win rate but different latency
        for i in range(6):
            bench_id = f"01HTIE{i:021d}"
            bm = _make_benchmark(bench_id, tags=["research"])
            await storage.save_benchmark(bm)

            exec1_id = f"01HETIE{i:020d}A"
            exec2_id = f"01HETIE{i:020d}B"

            await storage.save_execution(
                _make_execution(
                    exec1_id,
                    bench_id,
                    "agent_a",
                    DeploymentType.LOCAL_DOCKER,
                    total_latency_ms=1000.0,
                    estimated_cost_usd=0.01,
                )
            )
            await storage.save_execution(
                _make_execution(
                    exec2_id,
                    bench_id,
                    "agent_b",
                    DeploymentType.VIRTUAL_MACHINE,
                    total_latency_ms=5000.0,
                    estimated_cost_usd=0.01,
                )
            )

            # 3 prefer agent_a, 3 prefer agent_b → tied win rate
            if i < 3:
                pref_agent = "agent_a"
                pref_deploy = DeploymentType.LOCAL_DOCKER
            else:
                pref_agent = "agent_b"
                pref_deploy = DeploymentType.VIRTUAL_MACHINE

            eval_id = f"01HEVTIE{i:019d}"
            await storage.save_evaluation(
                _make_evaluation(eval_id, bench_id, pref_agent, pref_deploy)
            )

        gen = ReportGenerator(storage)
        report = await gen.generate("2024-06-01", "2024-06-30")

        # Both have 50% win rate, agent_a has lower latency (1000ms vs 5000ms)
        lines = report.split("\n")
        rec_start = next(i for i, line in enumerate(lines) if line.startswith("## Recommendations"))
        rec_section = "\n".join(lines[rec_start:])
        assert "agent_a/local_docker" in rec_section

    async def test_low_sample_warning(self, storage):
        """Categories with fewer than 5 benchmarks get a warning."""
        # Seed only 3 benchmarks in 'debug' category
        for i in range(3):
            bench_id = f"01HWARN{i:020d}"
            bm = _make_benchmark(bench_id, tags=["debug"])
            await storage.save_benchmark(bm)

            exec_id = f"01HEWARN{i:019d}A"
            await storage.save_execution(
                _make_execution(exec_id, bench_id, "hermes", DeploymentType.LOCAL_DOCKER)
            )

            eval_id = f"01HEVWARN{i:018d}"
            await storage.save_evaluation(
                _make_evaluation(eval_id, bench_id, "hermes", DeploymentType.LOCAL_DOCKER)
            )

        gen = ReportGenerator(storage)
        report = await gen.generate("2024-06-01", "2024-06-30")

        assert "⚠️ Warning" in report
        assert "fewer than 5" in report

    async def test_low_sample_no_recommendation(self, storage):
        """Categories with fewer than 5 benchmarks have no recommendation."""
        # Seed only 3 benchmarks in 'debug' category
        for i in range(3):
            bench_id = f"01HNOREC{i:019d}"
            bm = _make_benchmark(bench_id, tags=["small"])
            await storage.save_benchmark(bm)

            exec_id = f"01HENOREC{i:018d}A"
            await storage.save_execution(
                _make_execution(exec_id, bench_id, "hermes", DeploymentType.LOCAL_DOCKER)
            )

            eval_id = f"01HEVNOREC{i:017d}"
            await storage.save_evaluation(
                _make_evaluation(eval_id, bench_id, "hermes", DeploymentType.LOCAL_DOCKER)
            )

        gen = ReportGenerator(storage)
        report = await gen.generate("2024-06-01", "2024-06-30")

        # Recommendations section should not include 'small' category
        lines = report.split("\n")
        rec_start = next(i for i, line in enumerate(lines) if line.startswith("## Recommendations"))
        rec_section = "\n".join(lines[rec_start:])
        assert "small" not in rec_section

    async def test_empty_date_range(self, storage):
        """Report for a date range with no data produces valid output."""
        gen = ReportGenerator(storage)
        report = await gen.generate("2025-01-01", "2025-01-31")

        assert "0 Benchmarks Evaluated" in report
        assert "No categories have sufficient data" in report

    async def test_date_range_filtering(self, storage):
        """Only benchmarks within the date range are included."""
        # Benchmark inside range
        bm_in = _make_benchmark(
            "01HRANGE000000000000001",
            tags=["coding"],
            created_at=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        )
        await storage.save_benchmark(bm_in)
        await storage.save_execution(
            _make_execution(
                "01HERANGE00000000000001A",
                bm_in.id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
            )
        )
        await storage.save_evaluation(
            _make_evaluation(
                "01HEVRANGE0000000000001",
                bm_in.id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
            )
        )

        # Benchmark outside range
        bm_out = _make_benchmark(
            "01HRANGE000000000000002",
            tags=["coding"],
            created_at=datetime(2024, 7, 20, 12, 0, 0, tzinfo=UTC),
        )
        await storage.save_benchmark(bm_out)
        await storage.save_execution(
            _make_execution(
                "01HERANGE00000000000002A",
                bm_out.id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
            )
        )
        await storage.save_evaluation(
            _make_evaluation(
                "01HEVRANGE0000000000002",
                bm_out.id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
            )
        )

        gen = ReportGenerator(storage)
        report = await gen.generate("2024-06-01", "2024-06-30")

        assert "1 Benchmarks Evaluated" in report

    async def test_uncategorized_benchmarks(self, storage):
        """Benchmarks with no tags appear under 'uncategorized'."""
        bench_id = "01HUNCAT000000000000001"
        bm = _make_benchmark(bench_id, tags=[])
        await storage.save_benchmark(bm)

        await storage.save_execution(
            _make_execution(
                "01HEUNCAT0000000000001A",
                bench_id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
            )
        )
        await storage.save_evaluation(
            _make_evaluation(
                "01HEVUNCAT000000000001",
                bench_id,
                "hermes",
                DeploymentType.LOCAL_DOCKER,
            )
        )

        gen = ReportGenerator(storage)
        report = await gen.generate("2024-06-01", "2024-06-30")

        assert "## uncategorized" in report
