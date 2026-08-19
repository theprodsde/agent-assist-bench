"""Property tests for LLM metrics persistence (Task 12.3).

Property 17: LLM Metrics Persistence — hypothesis-generated LLMMetrics fields
persist correctly through SQLite save/retrieve cycles.
"""

from __future__ import annotations

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
    Execution,
    ExecutionResult,
    LLMMetrics,
)
from benchmark.storage.manager import StorageManager

# --- Strategies ---

_model_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd"), whitelist_characters="-_./"),
    min_size=1,
    max_size=50,
)
_token_counts = st.integers(min_value=0, max_value=100000)
_costs = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)


@st.composite
def llm_metrics_strategy(draw: st.DrawFn) -> LLMMetrics:
    """Generate random LLMMetrics with valid values."""
    model = draw(_model_names)
    prompt_tokens = draw(_token_counts)
    completion_tokens = draw(_token_counts)
    total_tokens = draw(st.just(prompt_tokens + completion_tokens) | _token_counts)
    api_latency_ms = draw(
        st.floats(min_value=0.1, max_value=60000.0, allow_nan=False, allow_infinity=False)
    )
    estimated_cost_usd = draw(_costs)
    return LLMMetrics(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        api_latency_ms=api_latency_ms,
        estimated_cost_usd=estimated_cost_usd,
    )


async def _setup_storage(base_dir: Path) -> StorageManager:
    """Create and initialize a temporary StorageManager."""
    db_path = base_dir / "test.db"
    storage = StorageManager(db_path)
    await storage.initialize()
    return storage


# --- Property 17: LLM Metrics Persistence ---


@settings(max_examples=10)
@given(metrics=llm_metrics_strategy())
@pytest.mark.property
async def test_llm_metrics_persistence(metrics: LLMMetrics) -> None:
    """LLM metrics persist exactly through save/retrieve cycle."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            # Create a benchmark to associate the execution with
            benchmark = Benchmark(
                source="cli",
                prompt="LLM metrics persistence test",
                status=BenchmarkStatus.COMPLETED,
                created_at=datetime.now(UTC),
            )
            await storage.save_benchmark(benchmark)

            # Create execution with the generated LLM metrics
            now = datetime.now(UTC)
            execution = Execution(
                benchmark_id=benchmark.id,
                agent_name="test-agent",
                agent_version="1.0.0",
                deployment=DeploymentMetrics(
                    provider="docker",
                    deployment_type=DeploymentType.LOCAL_DOCKER,
                    total_latency_ms=200.0,
                ),
                llm=metrics,
                result=ExecutionResult(raw_response="test response"),
                started_at=now,
                completed_at=now,
                success=True,
            )
            await storage.save_execution(execution)

            # Retrieve and verify
            retrieved_executions = await storage.get_executions(benchmark.id)
            assert len(retrieved_executions) == 1

            retrieved = retrieved_executions[0]
            assert retrieved.llm is not None

            # Verify all fields match exactly
            assert retrieved.llm.model == metrics.model
            assert retrieved.llm.prompt_tokens == metrics.prompt_tokens
            assert retrieved.llm.completion_tokens == metrics.completion_tokens
            assert retrieved.llm.total_tokens == metrics.total_tokens

            # Float comparisons with tolerance for SQLite REAL representation
            if metrics.api_latency_ms is not None:
                assert retrieved.llm.api_latency_ms is not None
                assert abs(retrieved.llm.api_latency_ms - metrics.api_latency_ms) < 1e-6
            if metrics.estimated_cost_usd is not None:
                assert retrieved.llm.estimated_cost_usd is not None
                assert abs(retrieved.llm.estimated_cost_usd - metrics.estimated_cost_usd) < 1e-6
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@settings(max_examples=10)
@given(metrics=llm_metrics_strategy())
@pytest.mark.property
async def test_llm_metrics_none_fields_handled(metrics: LLMMetrics) -> None:
    """Execution without LLM metrics persists with llm=None correctly."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        storage = await _setup_storage(tmp_dir)
        try:
            benchmark = Benchmark(
                source="api",
                prompt="No LLM metrics test",
                status=BenchmarkStatus.COMPLETED,
                created_at=datetime.now(UTC),
            )
            await storage.save_benchmark(benchmark)

            # Execution WITHOUT LLM metrics
            now = datetime.now(UTC)
            execution_no_llm = Execution(
                benchmark_id=benchmark.id,
                agent_name="no-llm-agent",
                agent_version="1.0.0",
                deployment=DeploymentMetrics(
                    provider="vm",
                    deployment_type=DeploymentType.VIRTUAL_MACHINE,
                    total_latency_ms=300.0,
                ),
                llm=None,
                result=ExecutionResult(raw_response="no llm response"),
                started_at=now,
                completed_at=now,
                success=True,
            )
            await storage.save_execution(execution_no_llm)

            # Retrieve and verify llm is None
            retrieved = await storage.get_executions(benchmark.id)
            assert len(retrieved) == 1
            assert retrieved[0].llm is None
            assert retrieved[0].agent_name == "no-llm-agent"
        finally:
            await storage.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
