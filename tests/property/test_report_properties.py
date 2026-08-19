"""Property tests for report statistical accuracy (Task 9.2).

Property 16: Report Statistical Accuracy — verify win rates in generated Markdown
match expected percentages from known evaluation distributions.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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

# --- Strategies ---


@st.composite
def win_distribution(draw: st.DrawFn) -> tuple[int, int]:
    """Generate a win distribution: (agent_a_wins, agent_b_wins) summing to 2-6 total."""
    total = draw(st.integers(min_value=2, max_value=6))
    a_wins = draw(st.integers(min_value=0, max_value=total))
    b_wins = total - a_wins
    return (a_wins, b_wins)


async def _setup_storage(base_dir: Path) -> StorageManager:
    """Create and initialize a temporary StorageManager."""
    db_path = base_dir / "test.db"
    storage = StorageManager(db_path)
    await storage.initialize()
    return storage


def _make_execution(benchmark_id: str, agent_name: str, success: bool = True) -> Execution:
    """Create a minimal valid Execution."""
    now = datetime.now(UTC)
    return Execution(
        benchmark_id=benchmark_id,
        agent_name=agent_name,
        agent_version="1.0.0",
        deployment=DeploymentMetrics(
            provider="docker",
            deployment_type=DeploymentType.LOCAL_DOCKER,
            total_latency_ms=150.0,
        ),
        llm=LLMMetrics(model="gpt-4", prompt_tokens=50, completion_tokens=100, total_tokens=150),
        result=ExecutionResult(
            raw_response="response" if success else "",
            errors=[] if success else ["execution failed"],
        ),
        started_at=now,
        completed_at=now,
        success=success,
    )


# --- Property 16: Report Statistical Accuracy ---


@settings(max_examples=10)
@given(dist=win_distribution())
@pytest.mark.property
async def test_report_statistical_accuracy(dist: tuple[int, int]) -> None:
    """Win rates in the generated report match expected percentages within rounding."""
    agent_a_wins, agent_b_wins = dist
    total = agent_a_wins + agent_b_wins

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            # Create benchmarks: one per "round", each has two executions (agent_a, agent_b)
            # The evaluation picks the "winner" for each round.
            for i in range(total):
                benchmark = Benchmark(
                    source="cli",
                    prompt=f"Benchmark {i} for report test",
                    status=BenchmarkStatus.COMPLETED,
                    created_at=datetime(2024, 7, 1, 10, i, 0, tzinfo=UTC),
                    tags=["test-category"],
                )
                await storage.save_benchmark(benchmark)

                exec_a = _make_execution(benchmark.id, "agent_a")
                exec_b = _make_execution(benchmark.id, "agent_b")
                await storage.save_execution(exec_a)
                await storage.save_execution(exec_b)

                # Pick winner based on distribution
                preferred = "agent_a" if i < agent_a_wins else "agent_b"

                evaluation = Evaluation(
                    benchmark_id=benchmark.id,
                    rating=4,
                    preferred_agent=preferred,
                    preferred_deployment=DeploymentType.LOCAL_DOCKER,
                )
                await storage.save_evaluation(evaluation)

            # Generate report
            generator = ReportGenerator(storage)
            report_text = await generator.generate("2024-07-01", "2024-07-01")

            # Parse win rates from Markdown table rows
            # Pattern: | agent_name/deployment | XX.XX% | ...
            win_rates: dict[str, float] = {}
            for match in re.finditer(r"\|\s*([\w_-]+/[\w_]+)\s*\|\s*([\d.]+)%", report_text):
                pair_key = match.group(1)
                rate = float(match.group(2))
                win_rates[pair_key] = rate

            # Expected win rates
            expected_a = round((agent_a_wins / total * 100) if total > 0 else 0.0, 2)
            expected_b = round((agent_b_wins / total * 100) if total > 0 else 0.0, 2)

            # Verify the parsed rates match (within floating-point rounding)
            agent_a_key = "agent_a/local_docker"
            agent_b_key = "agent_b/local_docker"

            assert agent_a_key in win_rates, (
                f"agent_a not found in report. Keys: {list(win_rates.keys())}"
            )
            assert agent_b_key in win_rates, (
                f"agent_b not found in report. Keys: {list(win_rates.keys())}"
            )

            assert abs(win_rates[agent_a_key] - expected_a) <= 0.01, (
                f"agent_a win rate {win_rates[agent_a_key]} != expected {expected_a}"
            )
            assert abs(win_rates[agent_b_key] - expected_b) <= 0.01, (
                f"agent_b win rate {win_rates[agent_b_key]} != expected {expected_b}"
            )
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
