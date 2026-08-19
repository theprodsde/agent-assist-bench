"""Unit tests for EvaluationService business rules.

Each test validates a specific requirement from the evaluation domain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from benchmark.evaluation.exceptions import (
    BenchmarkNotCompletedError,
    BenchmarkNotFoundError,
    EvaluationConflictError,
    EvaluationImmutableError,
    InvalidPreferredAgentError,
)
from benchmark.evaluation.service import EvaluationService
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Evaluation,
    Execution,
    ExecutionResult,
)


def _make_benchmark(
    benchmark_id: str = "01BENCH000000000000000001",
    status: BenchmarkStatus = BenchmarkStatus.COMPLETED,
) -> Benchmark:
    return Benchmark(
        id=benchmark_id,
        source="cli",
        prompt="Test prompt",
        status=status,
        created_at=datetime.now(UTC),
    )


def _make_evaluation(
    benchmark_id: str = "01BENCH000000000000000001",
    preferred_agent: str | None = None,
) -> Evaluation:
    return Evaluation(
        benchmark_id=benchmark_id,
        rating=4,
        preferred_agent=preferred_agent,
    )


def _make_execution(benchmark_id: str, agent_name: str) -> Execution:
    return Execution(
        benchmark_id=benchmark_id,
        agent_name=agent_name,
        agent_version="1.0.0",
        deployment=DeploymentMetrics(
            provider="local",
            deployment_type=DeploymentType.LOCAL_DOCKER,
            total_latency_ms=100.0,
        ),
        result=ExecutionResult(raw_response="response"),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        success=True,
    )


@pytest.fixture
def storage() -> AsyncMock:
    """Create a mock StorageManager with default happy-path behavior."""
    mock = AsyncMock()
    mock.get_benchmark = AsyncMock(return_value=_make_benchmark())
    mock.get_evaluation = AsyncMock(return_value=None)
    mock.get_executions = AsyncMock(return_value=[])
    mock.save_evaluation = AsyncMock()
    return mock


@pytest.fixture
def service(storage: AsyncMock) -> EvaluationService:
    return EvaluationService(storage)


class TestBenchmarkNotFound:
    """Req 6.2: Reject evaluation for non-existent benchmark."""

    async def test_raises_when_benchmark_missing(
        self, service: EvaluationService, storage: AsyncMock
    ) -> None:
        storage.get_benchmark.return_value = None
        evaluation = _make_evaluation(benchmark_id="nonexistent")

        with pytest.raises(BenchmarkNotFoundError) as exc_info:
            await service.submit(evaluation)

        assert exc_info.value.benchmark_id == "nonexistent"
        assert "not found" in str(exc_info.value).lower()
        storage.save_evaluation.assert_not_called()


class TestBenchmarkNotCompleted:
    """Req 6.3: Reject evaluation for PENDING, RUNNING, or FAILED benchmarks."""

    @pytest.mark.parametrize(
        "status",
        [BenchmarkStatus.PENDING, BenchmarkStatus.RUNNING, BenchmarkStatus.FAILED],
    )
    async def test_rejects_non_evaluable_status(
        self, service: EvaluationService, storage: AsyncMock, status: BenchmarkStatus
    ) -> None:
        storage.get_benchmark.return_value = _make_benchmark(status=status)
        evaluation = _make_evaluation()

        with pytest.raises(BenchmarkNotCompletedError) as exc_info:
            await service.submit(evaluation)

        assert exc_info.value.status == str(status)
        assert "not yet completed" in str(exc_info.value).lower() or "COMPLETED" in str(
            exc_info.value
        )
        storage.save_evaluation.assert_not_called()

    @pytest.mark.parametrize(
        "status",
        [BenchmarkStatus.COMPLETED, BenchmarkStatus.PARTIALLY_FAILED],
    )
    async def test_accepts_evaluable_status(
        self, service: EvaluationService, storage: AsyncMock, status: BenchmarkStatus
    ) -> None:
        storage.get_benchmark.return_value = _make_benchmark(status=status)
        evaluation = _make_evaluation()

        result = await service.submit(evaluation)

        assert result == evaluation
        storage.save_evaluation.assert_called_once_with(evaluation)


class TestEvaluationConflict:
    """Req 6.4: Reject duplicate evaluations, preserve existing unchanged."""

    async def test_rejects_duplicate_evaluation(
        self, service: EvaluationService, storage: AsyncMock
    ) -> None:
        existing = _make_evaluation()
        storage.get_evaluation.return_value = existing
        new_evaluation = _make_evaluation()

        with pytest.raises(EvaluationConflictError) as exc_info:
            await service.submit(new_evaluation)

        assert exc_info.value.benchmark_id == existing.benchmark_id
        assert exc_info.value.existing_evaluation_id == existing.id
        storage.save_evaluation.assert_not_called()


class TestInvalidPreferredAgent:
    """Req 6.5: preferred_agent must match an agent that executed."""

    async def test_rejects_unmatched_preferred_agent(
        self, service: EvaluationService, storage: AsyncMock
    ) -> None:
        benchmark_id = "01BENCH000000000000000001"
        storage.get_executions.return_value = [
            _make_execution(benchmark_id, "hermes"),
            _make_execution(benchmark_id, "openclaw"),
        ]
        evaluation = _make_evaluation(benchmark_id=benchmark_id, preferred_agent="unknown_agent")

        with pytest.raises(InvalidPreferredAgentError) as exc_info:
            await service.submit(evaluation)

        assert exc_info.value.preferred_agent == "unknown_agent"
        assert "hermes" in exc_info.value.available_agents
        assert "openclaw" in exc_info.value.available_agents
        storage.save_evaluation.assert_not_called()

    async def test_accepts_valid_preferred_agent(
        self, service: EvaluationService, storage: AsyncMock
    ) -> None:
        benchmark_id = "01BENCH000000000000000001"
        storage.get_executions.return_value = [
            _make_execution(benchmark_id, "hermes"),
            _make_execution(benchmark_id, "openclaw"),
        ]
        evaluation = _make_evaluation(benchmark_id=benchmark_id, preferred_agent="hermes")

        result = await service.submit(evaluation)

        assert result == evaluation
        storage.save_evaluation.assert_called_once()

    async def test_skips_validation_when_no_preferred_agent(
        self, service: EvaluationService, storage: AsyncMock
    ) -> None:
        evaluation = _make_evaluation(preferred_agent=None)

        result = await service.submit(evaluation)

        assert result == evaluation
        storage.get_executions.assert_not_called()


class TestImmutability:
    """Req 6.6: Evaluations are immutable once submitted."""

    async def test_guard_immutable_rejects_modification(self, service: EvaluationService) -> None:
        with pytest.raises(EvaluationImmutableError) as exc_info:
            await service.guard_immutable("eval-123")

        assert exc_info.value.evaluation_id == "eval-123"
        assert "immutable" in str(exc_info.value).lower()
