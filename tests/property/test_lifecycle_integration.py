"""Integration tests for full benchmark lifecycle (Task 12.2).

Tests the complete flow: create → execute → evaluate → export → report.
Also tests that one agent failing doesn't block others.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003

import httpx
import pytest

from benchmark.agents.base import AgentRequest, AgentResponse
from benchmark.agents.registry import AgentRegistry
from benchmark.evaluation.service import EvaluationService
from benchmark.export.daily import DailyExporter
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    Evaluation,
    LLMMetrics,
)
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager

# --- Mock Agent Adapters ---


class MockSuccessAgent:
    """Agent that always succeeds."""

    def __init__(self, name: str = "success-agent", version: str = "1.0.0") -> None:
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            content=f"Success response to: {request.prompt[:50]}",
            llm_metrics=LLMMetrics(
                model="mock-model",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                estimated_cost_usd=0.001,
            ),
            errors=[],
        )

    async def health_check(self) -> bool:
        return True


class MockFailureAgent:
    """Agent that always fails."""

    def __init__(self, name: str = "failure-agent", version: str = "1.0.0") -> None:
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        raise RuntimeError("Simulated agent failure")

    async def health_check(self) -> bool:
        return True


class MockHTTPAgent:
    """Agent backed by httpx mock transport for endpoint simulation."""

    def __init__(
        self,
        name: str,
        version: str,
        transport: httpx.MockTransport,
        endpoint: str = "http://mock-agent/execute",
    ) -> None:
        self._name = name
        self._version = version
        self._client = httpx.AsyncClient(transport=transport)
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        response = await self._client.post(
            self._endpoint,
            json={"prompt": request.prompt},
        )
        if response.status_code == 200:
            data = response.json()
            return AgentResponse(content=data.get("content", ""), errors=[])
        return AgentResponse(content="", errors=[f"HTTP {response.status_code}"])

    async def health_check(self) -> bool:
        return True


async def _setup_storage(tmp_path: Path) -> StorageManager:
    """Create and initialize a temporary StorageManager."""
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path)
    await storage.initialize()
    return storage


# --- Test: Full lifecycle ---


@pytest.mark.integration
async def test_full_lifecycle_create_execute_evaluate_export_report(tmp_path: Path) -> None:
    """End-to-end: create benchmark → execute → evaluate → export → report."""
    storage = await _setup_storage(tmp_path)
    try:
        # 1. Create benchmark
        benchmark = Benchmark(
            source="cli",
            prompt="Full lifecycle integration test prompt",
            status=BenchmarkStatus.PENDING,
            created_at=datetime(2024, 8, 1, 12, 0, 0, tzinfo=UTC),
            tags=["integration"],
        )
        await storage.save_benchmark(benchmark)
        await storage.update_status(benchmark.id, BenchmarkStatus.RUNNING)

        # 2. Execute via runner
        registry = AgentRegistry()
        agent = MockSuccessAgent(name="hermes")
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://hermes:8080")

        config = RunnerConfig(
            execution_order=[("hermes", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=30.0,
        )
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(benchmark)
        assert status == BenchmarkStatus.COMPLETED

        # 3. Evaluate
        eval_service = EvaluationService(storage)
        evaluation = Evaluation(
            benchmark_id=benchmark.id,
            rating=5,
            preferred_agent="hermes",
            preferred_deployment=DeploymentType.LOCAL_DOCKER,
            notes="Excellent response",
        )
        await eval_service.submit(evaluation)

        # 4. Export
        export_dir = tmp_path / "exports"
        exporter = DailyExporter(storage, export_dir=export_dir)
        manifest = await exporter.export_day("2024-08-01")
        assert manifest.benchmark_count == 1
        assert manifest.execution_count == 1
        assert manifest.evaluation_count == 1
        assert len(manifest.files) > 0

        # 5. Report
        generator = ReportGenerator(storage)
        report = await generator.generate("2024-08-01", "2024-08-01")
        assert "hermes" in report
        assert "integration" in report
        assert "100.0%" in report  # hermes wins 1/1 = 100%
    finally:
        await storage.close()


# --- Test: Agent failure doesn't block others ---


@pytest.mark.integration
async def test_agent_failure_does_not_block_others(tmp_path: Path) -> None:
    """One agent failing does not prevent other agents from executing."""
    storage = await _setup_storage(tmp_path)
    try:
        benchmark = Benchmark(
            source="api",
            prompt="Failure isolation test",
            status=BenchmarkStatus.PENDING,
            created_at=datetime(2024, 8, 2, 10, 0, 0, tzinfo=UTC),
        )
        await storage.save_benchmark(benchmark)
        await storage.update_status(benchmark.id, BenchmarkStatus.RUNNING)

        # Register one failing and one succeeding agent
        registry = AgentRegistry()
        fail_agent = MockFailureAgent(name="bad-agent")
        success_agent = MockSuccessAgent(name="good-agent")
        registry.register(fail_agent, DeploymentType.LOCAL_DOCKER, "http://bad:8080")
        registry.register(success_agent, DeploymentType.MANAGED_CONTAINER, "http://good:8080")

        config = RunnerConfig(
            execution_order=[
                ("bad-agent", DeploymentType.LOCAL_DOCKER),
                ("good-agent", DeploymentType.MANAGED_CONTAINER),
            ],
            delay_between_seconds=0.0,
            timeout_seconds=10.0,
        )
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(benchmark)

        # Mixed result: one failure, one success → PARTIALLY_FAILED
        assert status == BenchmarkStatus.PARTIALLY_FAILED

        # Verify both executions were saved
        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 2

        # First agent failed, second succeeded
        bad_exec = next(e for e in executions if e.agent_name == "bad-agent")
        good_exec = next(e for e in executions if e.agent_name == "good-agent")
        assert bad_exec.success is False
        assert good_exec.success is True
    finally:
        await storage.close()


# --- Test: Mock HTTP transport agent ---


@pytest.mark.integration
async def test_mock_http_transport_agent(tmp_path: Path) -> None:
    """Agent backed by httpx MockTransport can complete benchmark execution."""
    storage = await _setup_storage(tmp_path)
    try:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"content": "Mock HTTP response"},
            )

        transport = httpx.MockTransport(handler)
        http_agent = MockHTTPAgent(name="http-agent", version="2.0.0", transport=transport)

        registry = AgentRegistry()
        registry.register(http_agent, DeploymentType.VIRTUAL_MACHINE, "http://mock-agent/execute")

        benchmark = Benchmark(
            source="cli",
            prompt="HTTP transport test prompt",
            status=BenchmarkStatus.PENDING,
            created_at=datetime(2024, 8, 3, 8, 0, 0, tzinfo=UTC),
        )
        await storage.save_benchmark(benchmark)
        await storage.update_status(benchmark.id, BenchmarkStatus.RUNNING)

        config = RunnerConfig(
            execution_order=[("http-agent", DeploymentType.VIRTUAL_MACHINE)],
            delay_between_seconds=0.0,
            timeout_seconds=10.0,
        )
        runner = BenchmarkRunner(registry, storage, config)
        status = await runner.run(benchmark)
        assert status == BenchmarkStatus.COMPLETED

        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 1
        assert executions[0].success is True
        assert "Mock HTTP response" in executions[0].result.raw_response
    finally:
        await storage.close()
