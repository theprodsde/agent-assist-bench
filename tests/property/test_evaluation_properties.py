"""Property tests for evaluation uniqueness and precondition (Task 11.2).

Property 5: Evaluation Uniqueness — duplicate evaluation raises EvaluationConflictError.
Property 6: Evaluation Precondition — evaluation on non-terminal benchmark raises error.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.evaluation.exceptions import (
    BenchmarkNotCompletedError,
    EvaluationConflictError,
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
from benchmark.storage.manager import StorageManager

# --- Strategies ---

_ratings = st.integers(min_value=1, max_value=5)
_non_evaluable_statuses = st.sampled_from(
    [
        BenchmarkStatus.PENDING,
        BenchmarkStatus.RUNNING,
        BenchmarkStatus.FAILED,
    ]
)


async def _setup_storage(base_dir: Path) -> StorageManager:
    """Create and initialize a temporary StorageManager."""
    db_path = base_dir / "test.db"
    storage = StorageManager(db_path)
    await storage.initialize()
    return storage


def _make_execution(benchmark_id: str, agent_name: str) -> Execution:
    """Create a minimal valid Execution."""
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
        result=ExecutionResult(raw_response="response text"),
        started_at=now,
        completed_at=now,
        success=True,
    )


# --- Property 5: Evaluation Uniqueness ---


@settings(max_examples=10)
@given(rating1=_ratings, rating2=_ratings)
@pytest.mark.property
async def test_evaluation_uniqueness(rating1: int, rating2: int) -> None:
    """Submitting a second evaluation for the same benchmark raises EvaluationConflictError."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            service = EvaluationService(storage)

            # Create a COMPLETED benchmark with an execution
            benchmark = Benchmark(
                source="cli",
                prompt="Uniqueness test prompt",
                status=BenchmarkStatus.COMPLETED,
                created_at=datetime.now(UTC),
            )
            await storage.save_benchmark(benchmark)

            execution = _make_execution(benchmark.id, "hermes")
            await storage.save_execution(execution)

            # First evaluation should succeed
            eval1 = Evaluation(
                benchmark_id=benchmark.id,
                rating=rating1,
                preferred_agent="hermes",
                preferred_deployment=DeploymentType.LOCAL_DOCKER,
            )
            result = await service.submit(eval1)
            assert result.benchmark_id == benchmark.id

            # Second evaluation should raise conflict
            eval2 = Evaluation(
                benchmark_id=benchmark.id,
                rating=rating2,
                preferred_agent="hermes",
                preferred_deployment=DeploymentType.LOCAL_DOCKER,
            )
            with pytest.raises(EvaluationConflictError) as exc_info:
                await service.submit(eval2)

            assert exc_info.value.benchmark_id == benchmark.id
            assert exc_info.value.existing_evaluation_id == eval1.id
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- Property 6: Evaluation Precondition ---


@settings(max_examples=10)
@given(status=_non_evaluable_statuses, rating=_ratings)
@pytest.mark.property
async def test_evaluation_precondition(status: BenchmarkStatus, rating: int) -> None:
    """Evaluating a PENDING/RUNNING/FAILED benchmark raises BenchmarkNotCompletedError."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            service = EvaluationService(storage)

            # Create a benchmark with the given non-evaluable status
            benchmark = Benchmark(
                source="api",
                prompt="Precondition test prompt",
                status=status,
                created_at=datetime.now(UTC),
            )
            await storage.save_benchmark(benchmark)

            # Attempt evaluation — should be rejected
            evaluation = Evaluation(
                benchmark_id=benchmark.id,
                rating=rating,
            )
            with pytest.raises(BenchmarkNotCompletedError) as exc_info:
                await service.submit(evaluation)

            assert exc_info.value.benchmark_id == benchmark.id
            assert exc_info.value.status == str(status)
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
