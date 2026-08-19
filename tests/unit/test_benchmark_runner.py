"""Unit tests for BenchmarkRunner — sequential execution, delays, timeouts, status."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from benchmark.agents.base import AgentRequest, AgentResponse
from benchmark.agents.registry import AgentRegistry
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    LLMMetrics,
)
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager

# --- Test helpers ---


class MockAgent:
    """A mock agent that records calls and returns configured responses."""

    def __init__(
        self,
        name: str = "mock-agent",
        version: str = "1.0.0",
        response: AgentResponse | None = None,
        health_ok: bool = True,
        execute_delay: float = 0.0,
        should_raise: Exception | None = None,
        health_raise: Exception | None = None,
    ):
        self._name = name
        self._version = version
        self._response = response or AgentResponse(content="OK", errors=[])
        self._health_ok = health_ok
        self._execute_delay = execute_delay
        self._should_raise = should_raise
        self._health_raise = health_raise
        self.execute_calls: list[AgentRequest] = []
        self.health_check_calls: int = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        self.execute_calls.append(request)
        if self._execute_delay > 0:
            await asyncio.sleep(self._execute_delay)
        if self._should_raise:
            raise self._should_raise
        return self._response

    async def health_check(self) -> bool:
        self.health_check_calls += 1
        if self._health_raise:
            raise self._health_raise
        return self._health_ok


def make_benchmark(prompt: str = "Test prompt") -> Benchmark:
    """Create a minimal valid benchmark for testing."""
    return Benchmark(source="cli", prompt=prompt)


def make_storage_mock() -> StorageManager:
    """Create a mock StorageManager with async methods."""
    storage = AsyncMock(spec=StorageManager)
    storage.save_execution = AsyncMock()
    storage.update_status = AsyncMock()
    return storage


# --- RunnerConfig tests ---


class TestRunnerConfig:
    def test_default_values(self):
        config = RunnerConfig()
        assert config.delay_between_seconds == 2.0
        assert config.timeout_seconds == 300.0
        assert config.execution_order == []

    def test_valid_delay_range(self):
        RunnerConfig(delay_between_seconds=0.0)
        RunnerConfig(delay_between_seconds=60.0)
        RunnerConfig(delay_between_seconds=30.0)

    def test_invalid_delay_below_range(self):
        with pytest.raises(ValueError, match="delay_between_seconds"):
            RunnerConfig(delay_between_seconds=-0.1)

    def test_invalid_delay_above_range(self):
        with pytest.raises(ValueError, match="delay_between_seconds"):
            RunnerConfig(delay_between_seconds=60.1)

    def test_valid_timeout_range(self):
        RunnerConfig(timeout_seconds=1)
        RunnerConfig(timeout_seconds=3600)

    def test_invalid_timeout_below_range(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            RunnerConfig(timeout_seconds=0)

    def test_invalid_timeout_above_range(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            RunnerConfig(timeout_seconds=3601)


# --- BenchmarkRunner sequential execution tests ---


class TestBenchmarkRunnerSequential:
    """Tests for sequential execution ordering and delay behavior."""

    @pytest.mark.asyncio
    async def test_executes_agents_in_order(self):
        """Req 2.1: Execute in configured order."""
        agent_a = MockAgent(name="agent-a")
        agent_b = MockAgent(name="agent-b")

        registry = AgentRegistry()
        registry.register(agent_a, DeploymentType.LOCAL_DOCKER, "http://a")
        registry.register(agent_b, DeploymentType.VIRTUAL_MACHINE, "http://b")

        config = RunnerConfig(
            execution_order=[
                ("agent-a", DeploymentType.LOCAL_DOCKER),
                ("agent-b", DeploymentType.VIRTUAL_MACHINE),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        benchmark = make_benchmark()

        status = await runner.run(benchmark)

        assert status == BenchmarkStatus.COMPLETED
        assert len(agent_a.execute_calls) == 1
        assert len(agent_b.execute_calls) == 1
        # Both executions saved
        assert storage.save_execution.call_count == 2

    @pytest.mark.asyncio
    async def test_no_delay_before_first_execution(self):
        """Req 2.2: No delay before the first execution."""
        agent = MockAgent(name="agent-a")

        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent-a", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=5.0,  # Large delay, but first should skip it
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        benchmark = make_benchmark()

        start = time.perf_counter()
        await runner.run(benchmark)
        elapsed = time.perf_counter() - start

        # Should complete in well under 5 seconds (no delay for first)
        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_delay_applied_between_executions(self):
        """Req 2.2: Delay applied between consecutive executions."""
        agent_a = MockAgent(name="agent-a")
        agent_b = MockAgent(name="agent-b")

        registry = AgentRegistry()
        registry.register(agent_a, DeploymentType.LOCAL_DOCKER, "http://a")
        registry.register(agent_b, DeploymentType.VIRTUAL_MACHINE, "http://b")

        delay = 0.1  # Small but measurable
        config = RunnerConfig(
            execution_order=[
                ("agent-a", DeploymentType.LOCAL_DOCKER),
                ("agent-b", DeploymentType.VIRTUAL_MACHINE),
            ],
            delay_between_seconds=delay,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        benchmark = make_benchmark()

        start = time.perf_counter()
        await runner.run(benchmark)
        elapsed = time.perf_counter() - start

        # Should take at least the delay time
        assert elapsed >= delay * 0.9  # Allow small timing margin

    @pytest.mark.asyncio
    async def test_persists_each_result_before_next(self):
        """Req 2.9: Persist execution before proceeding to next."""
        call_order: list[str] = []

        agent_a = MockAgent(name="agent-a")
        agent_b = MockAgent(name="agent-b")

        registry = AgentRegistry()
        registry.register(agent_a, DeploymentType.LOCAL_DOCKER, "http://a")
        registry.register(agent_b, DeploymentType.VIRTUAL_MACHINE, "http://b")

        config = RunnerConfig(
            execution_order=[
                ("agent-a", DeploymentType.LOCAL_DOCKER),
                ("agent-b", DeploymentType.VIRTUAL_MACHINE),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()

        # Track save_execution calls relative to agent executions
        original_execute_a = agent_a.execute

        async def tracked_execute_a(request):
            call_order.append("execute_a")
            return await original_execute_a(request)

        agent_a.execute = tracked_execute_a

        original_execute_b = agent_b.execute

        async def tracked_execute_b(request):
            call_order.append("execute_b")
            return await original_execute_b(request)

        agent_b.execute = tracked_execute_b

        async def tracked_save(execution):
            call_order.append(f"save_{execution.agent_name}")

        storage.save_execution = tracked_save

        runner = BenchmarkRunner(registry, storage, config)
        benchmark = make_benchmark()

        await runner.run(benchmark)

        # Order must be: execute_a, save_a, execute_b, save_b
        assert call_order == [
            "execute_a",
            "save_agent-a",
            "execute_b",
            "save_agent-b",
        ]


# --- Status determination tests ---


class TestStatusDetermination:
    """Tests for status determination logic (Req 2.3-2.5)."""

    @pytest.mark.asyncio
    async def test_all_success_returns_completed(self):
        """Req 2.3: All succeed -> COMPLETED."""
        agent = MockAgent(name="agent-a")
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent-a", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_all_failures_returns_failed(self):
        """Req 2.5: All fail -> FAILED."""
        # Use unregistered agents to trigger skip (failure)
        registry = AgentRegistry()

        config = RunnerConfig(
            execution_order=[
                ("nonexistent-a", DeploymentType.LOCAL_DOCKER),
                ("nonexistent-b", DeploymentType.VIRTUAL_MACHINE),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.FAILED

    @pytest.mark.asyncio
    async def test_mixed_results_returns_partially_failed(self):
        """Req 2.4: Mixed -> PARTIALLY_FAILED."""
        agent = MockAgent(name="agent-a")
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[
                ("agent-a", DeploymentType.LOCAL_DOCKER),
                ("nonexistent", DeploymentType.VIRTUAL_MACHINE),  # Will skip
            ],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.PARTIALLY_FAILED

    @pytest.mark.asyncio
    async def test_empty_execution_order_returns_completed(self):
        """Edge case: no agents configured -> COMPLETED."""
        registry = AgentRegistry()
        config = RunnerConfig(
            execution_order=[],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )
        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.COMPLETED


# --- Timeout handling tests ---


class TestTimeoutHandling:
    """Tests for timeout enforcement (Req 2.7)."""

    @pytest.mark.asyncio
    async def test_timeout_marks_execution_as_failed(self):
        """Req 2.7: Timeout -> cancel, persist failure, continue."""
        slow_agent = MockAgent(name="slow", execute_delay=10.0)

        registry = AgentRegistry()
        registry.register(slow_agent, DeploymentType.LOCAL_DOCKER, "http://slow")

        config = RunnerConfig(
            execution_order=[("slow", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=1,  # Short timeout (minimum valid)
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.FAILED
        # Execution was saved with error
        storage.save_execution.assert_called_once()
        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.success is False
        assert any("timed out" in e.lower() for e in saved_exec.result.errors)

    @pytest.mark.asyncio
    async def test_timeout_continues_to_next_agent(self):
        """Req 2.7: After timeout, continue to next agent."""
        slow_agent = MockAgent(name="slow", execute_delay=10.0)
        fast_agent = MockAgent(name="fast")

        registry = AgentRegistry()
        registry.register(slow_agent, DeploymentType.LOCAL_DOCKER, "http://slow")
        registry.register(fast_agent, DeploymentType.VIRTUAL_MACHINE, "http://fast")

        config = RunnerConfig(
            execution_order=[
                ("slow", DeploymentType.LOCAL_DOCKER),
                ("fast", DeploymentType.VIRTUAL_MACHINE),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=1,  # Short timeout (minimum valid)
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        # One success, one timeout -> PARTIALLY_FAILED
        assert status == BenchmarkStatus.PARTIALLY_FAILED
        assert storage.save_execution.call_count == 2
        assert len(fast_agent.execute_calls) == 1


# --- Error resilience tests ---


class TestErrorResilience:
    """Tests for error handling and continuation (Req 12.1, 12.2)."""

    @pytest.mark.asyncio
    async def test_exception_marks_execution_as_failed(self):
        """Req 2.8: Exception -> persist error, count as failure."""
        error_agent = MockAgent(name="error-agent", should_raise=RuntimeError("Connection refused"))

        registry = AgentRegistry()
        registry.register(error_agent, DeploymentType.LOCAL_DOCKER, "http://err")

        config = RunnerConfig(
            execution_order=[("error-agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.FAILED
        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.success is False
        assert "RuntimeError" in saved_exec.result.errors[0]
        assert "Connection refused" in saved_exec.result.errors[0]

    @pytest.mark.asyncio
    async def test_exception_continues_to_next_agent(self):
        """Req 12.1: Continue after individual failure."""
        error_agent = MockAgent(name="error-agent", should_raise=RuntimeError("fail"))
        good_agent = MockAgent(name="good-agent")

        registry = AgentRegistry()
        registry.register(error_agent, DeploymentType.LOCAL_DOCKER, "http://err")
        registry.register(good_agent, DeploymentType.VIRTUAL_MACHINE, "http://good")

        config = RunnerConfig(
            execution_order=[
                ("error-agent", DeploymentType.LOCAL_DOCKER),
                ("good-agent", DeploymentType.VIRTUAL_MACHINE),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.PARTIALLY_FAILED
        assert len(good_agent.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_skip_unregistered_agent(self):
        """Req 2.6: Skip unregistered agents, persist skip record."""
        registry = AgentRegistry()
        config = RunnerConfig(
            execution_order=[("ghost", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(make_benchmark())

        assert status == BenchmarkStatus.FAILED
        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.success is False
        assert "not registered" in saved_exec.result.errors[0].lower()


# --- Metrics collection tests ---


class TestMetricsCollection:
    """Tests for timing metrics (Req 4.1, 4.2, 4.3, 4.6)."""

    @pytest.mark.asyncio
    async def test_records_total_latency(self):
        """Req 4.1: total_latency_ms measured with monotonic clock."""
        agent = MockAgent(name="agent", execute_delay=0.05)
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        await runner.run(make_benchmark())

        saved_exec = storage.save_execution.call_args[0][0]
        # Should be at least 50ms (agent has 50ms delay)
        assert saved_exec.deployment.total_latency_ms >= 40  # Small margin

    @pytest.mark.asyncio
    async def test_records_cold_start_ms(self):
        """Req 4.2: cold_start_ms measured via health check."""
        agent = MockAgent(name="agent")
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        await runner.run(make_benchmark())

        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.deployment.cold_start_ms is not None
        assert saved_exec.deployment.cold_start_ms >= 0
        assert agent.health_check_calls == 1

    @pytest.mark.asyncio
    async def test_health_check_failure_sets_cold_start_null(self):
        """Req 4.3: Health check failure -> cold_start_ms is None."""
        agent = MockAgent(name="agent", health_raise=ConnectionError("unreachable"))
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        await runner.run(make_benchmark())

        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.deployment.cold_start_ms is None
        # Execution still proceeds
        assert len(agent.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_records_utc_timestamps(self):
        """Req 4.6: started_at and completed_at are UTC."""
        agent = MockAgent(name="agent")
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        await runner.run(make_benchmark())

        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.started_at.tzinfo is not None
        assert saved_exec.completed_at.tzinfo is not None
        assert saved_exec.started_at <= saved_exec.completed_at

    @pytest.mark.asyncio
    async def test_persists_llm_metrics_when_present(self):
        """Req 4.4: Persist LLM metrics from agent response."""
        llm = LLMMetrics(model="gpt-4", prompt_tokens=100, completion_tokens=50, total_tokens=150)
        response = AgentResponse(content="result", llm_metrics=llm, errors=[])
        agent = MockAgent(name="agent", response=response)

        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        await runner.run(make_benchmark())

        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.llm is not None
        assert saved_exec.llm.model == "gpt-4"
        assert saved_exec.llm.total_tokens == 150

    @pytest.mark.asyncio
    async def test_llm_metrics_null_when_not_returned(self):
        """Req 4.5: LLM field is None when agent doesn't return metrics."""
        response = AgentResponse(content="result", errors=[])
        agent = MockAgent(name="agent", response=response)

        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://a")

        config = RunnerConfig(
            execution_order=[("agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10,
        )

        storage = make_storage_mock()
        runner = BenchmarkRunner(registry, storage, config)
        await runner.run(make_benchmark())

        saved_exec = storage.save_execution.call_args[0][0]
        assert saved_exec.llm is None
