"""Property tests for runner sequential execution, status determination, and timing (Tasks 6.4-6.6).

Tests:
- Property 1: Sequential Execution Ordering
- Property 2: Status Reflects Failure Count
- Property 3: Error Resilience — Continue After Failure
- Property 7: Execution Timing Invariant
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from benchmark.agents.base import AgentRequest, AgentResponse
from benchmark.agents.registry import AgentRegistry
from benchmark.models.domain import Benchmark, BenchmarkStatus, DeploymentType
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager


class RecordingAdapter:
    """Mock adapter that records call timestamps."""

    def __init__(self, name: str, version: str = "1.0.0", delay: float = 0.01) -> None:
        self._name = name
        self._version = version
        self._delay = delay
        self.call_timestamps: list[tuple[float, float]] = []  # (start, end)

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        start = time.perf_counter()
        await asyncio.sleep(self._delay)
        end = time.perf_counter()
        self.call_timestamps.append((start, end))
        return AgentResponse(content="ok")

    async def health_check(self) -> bool:
        return True


class FailingAdapter:
    """Mock adapter that raises on execute."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, request: AgentRequest) -> AgentResponse:
        raise RuntimeError(f"Intentional failure in {self._name}")

    async def health_check(self) -> bool:
        return True


async def _make_storage(db_path: Path) -> StorageManager:
    """Create and initialize a StorageManager at the given path."""
    mgr = StorageManager(db_path)
    await mgr.initialize()
    return mgr


# --- Property 1: Sequential Execution Ordering ---


@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    num_agents=st.integers(min_value=1, max_value=5),
)
@pytest.mark.asyncio
async def test_sequential_execution_ordering(
    num_agents: int,
    tmp_path: Path,
) -> None:
    """Each execution starts after the previous one completes."""
    with tempfile.TemporaryDirectory() as td:
        storage = await _make_storage(Path(td) / "seq.db")
        try:
            registry = AgentRegistry()
            adapters: list[RecordingAdapter] = []
            execution_order: list[tuple[str, DeploymentType]] = []

            for i in range(num_agents):
                name = f"agent-{i}"
                adapter = RecordingAdapter(name=name, delay=0.005)
                adapters.append(adapter)
                registry.register(adapter, DeploymentType.LOCAL_DOCKER, endpoint=f"http://{name}")
                execution_order.append((name, DeploymentType.LOCAL_DOCKER))

            config = RunnerConfig(
                execution_order=execution_order,
                delay_between_seconds=0.0,
                timeout_seconds=30,
            )
            runner = BenchmarkRunner(registry=registry, storage=storage, config=config)
            benchmark = Benchmark(source="cli", prompt="test sequential")

            # Save benchmark first so FK constraints are satisfied
            await storage.save_benchmark(benchmark)

            await runner.run(benchmark)

            # Verify sequential ordering: each adapter's start >= previous adapter's end
            all_timestamps = [a.call_timestamps[0] for a in adapters if a.call_timestamps]
            for i in range(1, len(all_timestamps)):
                prev_end = all_timestamps[i - 1][1]
                curr_start = all_timestamps[i][0]
                assert curr_start >= prev_end, f"Agent {i} started before agent {i - 1} completed"
        finally:
            await storage.close()


# --- Property 2: Status Reflects Failure Count ---


@settings(max_examples=20)
@given(
    failures=st.integers(min_value=0, max_value=10),
    total=st.integers(min_value=1, max_value=10),
)
def test_status_reflects_failure_count(failures: int, total: int) -> None:
    """_determine_status returns correct BenchmarkStatus for given failure/total."""
    # Clamp failures to [0, total]
    failures = min(failures, total)
    status = BenchmarkRunner._determine_status(failures, total)

    if failures == 0:
        assert status == BenchmarkStatus.COMPLETED
    elif failures == total:
        assert status == BenchmarkStatus.FAILED
    else:
        assert status == BenchmarkStatus.PARTIALLY_FAILED


# --- Property 3: Error Resilience — Continue After Failure ---


@pytest.mark.asyncio
async def test_error_resilience_continue_after_failure(tmp_path: Path) -> None:
    """When one adapter raises, subsequent adapters still execute."""
    storage = await _make_storage(tmp_path / "resilience.db")
    try:
        registry = AgentRegistry()

        good_before = RecordingAdapter(name="good-before", delay=0.005)
        bad_adapter = FailingAdapter(name="bad-agent")
        good_after = RecordingAdapter(name="good-after", delay=0.005)

        registry.register(good_before, DeploymentType.LOCAL_DOCKER, endpoint="http://a")
        registry.register(bad_adapter, DeploymentType.LOCAL_DOCKER, endpoint="http://b")
        registry.register(good_after, DeploymentType.LOCAL_DOCKER, endpoint="http://c")

        config = RunnerConfig(
            execution_order=[
                ("good-before", DeploymentType.LOCAL_DOCKER),
                ("bad-agent", DeploymentType.LOCAL_DOCKER),
                ("good-after", DeploymentType.LOCAL_DOCKER),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=30,
        )
        runner = BenchmarkRunner(registry=registry, storage=storage, config=config)
        benchmark = Benchmark(source="cli", prompt="resilience test")

        # Save benchmark first so FK constraints are satisfied
        await storage.save_benchmark(benchmark)

        status = await runner.run(benchmark)

        # Both good adapters should have been called
        assert len(good_before.call_timestamps) == 1
        assert len(good_after.call_timestamps) == 1
        # Status should be partially_failed (1 failure out of 3)
        assert status == BenchmarkStatus.PARTIALLY_FAILED
    finally:
        await storage.close()


# --- Property 7: Execution Timing Invariant ---


@pytest.mark.asyncio
async def test_execution_timing_positive_latency(tmp_path: Path) -> None:
    """All executions must have total_latency_ms > 0."""
    storage = await _make_storage(tmp_path / "timing.db")
    try:
        registry = AgentRegistry()
        adapter = RecordingAdapter(name="timed-agent", delay=0.01)
        registry.register(adapter, DeploymentType.LOCAL_DOCKER, endpoint="http://t")

        config = RunnerConfig(
            execution_order=[("timed-agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=30,
        )
        runner = BenchmarkRunner(registry=registry, storage=storage, config=config)
        benchmark = Benchmark(source="cli", prompt="timing test")

        # Save benchmark first so FK constraints are satisfied
        await storage.save_benchmark(benchmark)

        await runner.run(benchmark)

        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 1
        assert executions[0].deployment.total_latency_ms > 0
    finally:
        await storage.close()
