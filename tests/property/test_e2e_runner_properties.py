"""End-to-end property tests for runner invariants (Task 19.3).

Property 1: Sequential Execution Ordering
Property 3: Error Resilience — Continue After Failure
Property 8: Storage Round-Trip

Requirements: 2.1, 2.5, 2.8, 2.9, 5.2, 19.3
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.agents.base import AgentAdapter, AgentRequest, AgentResponse
from benchmark.agents.registry import AgentRegistry
from benchmark.models.domain import (
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    InputType,
    LLMMetrics,
)
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner, DeploymentResourceConfig
from benchmark.storage.manager import StorageManager

# ---------------------------------------------------------------------------
# Configurable mock agents for property tests
# ---------------------------------------------------------------------------


class SuccessAgent:
    """Agent that always succeeds with a deterministic response."""

    def __init__(self, agent_name: str, latency_ms: float = 5.0) -> None:
        self._name = agent_name
        self._latency = latency_ms / 1000.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, request: AgentRequest) -> AgentResponse:
        await asyncio.sleep(self._latency)
        attachment_info = ""
        if request.attachments:
            attachment_info = f"|attachments={len(request.attachments)}"
            for att in request.attachments:
                attachment_info += f"|{att.type.value}:{att.filename}"
        return AgentResponse(
            content=f"response-from-{self._name}:{request.prompt}{attachment_info}",
            errors=[],
            llm_metrics=LLMMetrics(
                model=f"model-{self._name}",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
            ),
        )

    async def health_check(self) -> bool:
        return True


class FailureAgent:
    """Agent that always fails with a deterministic error."""

    def __init__(self, agent_name: str) -> None:
        self._name = agent_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            content="",
            errors=[f"simulated_failure:{self._name}"],
        )

    async def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

agent_name_strategy = st.text(
    alphabet=st.characters(categories=("Ll",)), min_size=3, max_size=10
).map(lambda s: f"agent-{s}")

agent_count_strategy = st.integers(min_value=2, max_value=4)

attachment_strategy = st.fixed_dictionaries(
    {
        "type": st.sampled_from([InputType.IMAGE, InputType.AUDIO, InputType.VIDEO]),
        "filename": st.text(alphabet=st.characters(categories=("Ll",)), min_size=3, max_size=8).map(
            lambda s: f"{s}.dat"
        ),
    }
)

_MIME_MAP = {
    InputType.IMAGE: "image/png",
    InputType.AUDIO: "audio/mpeg",
    InputType.VIDEO: "video/mp4",
}


def _make_attachment(spec: dict) -> Attachment:
    """Create an Attachment from a hypothesis-generated spec."""
    input_type = spec["type"]
    return Attachment(
        type=input_type,
        filename=spec["filename"],
        mime_type=_MIME_MAP[input_type],
        size_bytes=100,
        content_base64="dGVzdA==",
    )


# ---------------------------------------------------------------------------
# Async helper to create storage with a unique temp directory per call
# ---------------------------------------------------------------------------


async def _create_storage() -> StorageManager:
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "prop_test.db"
    mgr = StorageManager(db_path=str(db_path))
    await mgr.initialize()
    return mgr


# ---------------------------------------------------------------------------
# Property 1: Sequential Execution Ordering
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    agent_count=agent_count_strategy,
    data=st.data(),
)
@pytest.mark.asyncio
async def test_sequential_execution_ordering(agent_count: int, data: st.DataObject) -> None:
    """Hypothesis generates 2-4 agent pairs. Verify no executions overlap:
    each started_at >= previous completed_at.
    """
    # Generate unique agent names
    names = [f"seq-agent-{i}" for i in range(agent_count)]

    storage = await _create_storage()
    try:
        registry = AgentRegistry()
        execution_order: list[tuple[str, DeploymentType]] = []

        for name in names:
            agent = SuccessAgent(agent_name=name, latency_ms=2.0)
            registry.register(agent, DeploymentType.LOCAL_DOCKER, f"http://{name}:9000")
            execution_order.append((name, DeploymentType.LOCAL_DOCKER))

        config = RunnerConfig(
            execution_order=execution_order,
            delay_between_seconds=0.0,
            timeout_seconds=10.0,
        )
        runner = BenchmarkRunner(registry=registry, storage=storage, config=config)

        benchmark = Benchmark(source="cli", prompt="Sequential ordering test")
        await storage.save_benchmark(benchmark)

        status = await runner.run(benchmark)
        assert status == BenchmarkStatus.COMPLETED

        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == agent_count

        # Verify sequential: each started_at >= previous completed_at
        for i in range(1, len(executions)):
            prev_completed = executions[i - 1].completed_at
            curr_started = executions[i].started_at
            assert curr_started >= prev_completed, (
                f"Execution {i} started at {curr_started} "
                f"before execution {i - 1} completed at {prev_completed}"
            )

        # Verify order matches configured execution_order
        for i, (name, _) in enumerate(execution_order):
            assert executions[i].agent_name == name
    finally:
        await storage.close()


# ---------------------------------------------------------------------------
# Property 3: Error Resilience — Continue After Failure
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    agent_count=agent_count_strategy,
    data=st.data(),
)
@pytest.mark.asyncio
async def test_error_resilience_continue_after_failure(
    agent_count: int, data: st.DataObject
) -> None:
    """Hypothesis injects failures at random positions. Verify ALL agents
    are attempted regardless of earlier failures.
    """
    # Determine which positions fail (at least one must fail)
    fail_positions = data.draw(
        st.lists(
            st.integers(min_value=0, max_value=agent_count - 1),
            min_size=1,
            max_size=agent_count,
            unique=True,
        )
    )

    storage = await _create_storage()
    try:
        registry = AgentRegistry()
        execution_order: list[tuple[str, DeploymentType]] = []

        for i in range(agent_count):
            name = f"resilience-agent-{i}"
            if i in fail_positions:
                agent: AgentAdapter = FailureAgent(agent_name=name)  # type: ignore[assignment]
            else:
                agent = SuccessAgent(agent_name=name)  # type: ignore[assignment]
            registry.register(agent, DeploymentType.LOCAL_DOCKER, f"http://{name}:9000")
            execution_order.append((name, DeploymentType.LOCAL_DOCKER))

        config = RunnerConfig(
            execution_order=execution_order,
            delay_between_seconds=0.0,
            timeout_seconds=10.0,
        )
        runner = BenchmarkRunner(registry=registry, storage=storage, config=config)

        benchmark = Benchmark(source="cli", prompt="Resilience test")
        await storage.save_benchmark(benchmark)

        await runner.run(benchmark)

        # Key invariant: ALL agents must be attempted
        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == agent_count, (
            f"Expected {agent_count} executions but got {len(executions)}. "
            f"Failure positions: {fail_positions}"
        )

        # Verify correct success/failure status at each position
        for i, ex in enumerate(executions):
            expected_name = f"resilience-agent-{i}"
            assert ex.agent_name == expected_name
            if i in fail_positions:
                assert ex.success is False
                assert len(ex.result.errors) > 0
            else:
                assert ex.success is True
    finally:
        await storage.close()


# ---------------------------------------------------------------------------
# Property 8: Storage Round-Trip
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    attachment_specs=st.lists(attachment_strategy, min_size=0, max_size=3),
    prompt=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
)
@pytest.mark.asyncio
async def test_storage_round_trip(
    attachment_specs: list[dict],
    prompt: str,
) -> None:
    """Hypothesis generates benchmarks with various attachments. Run through
    runner, retrieve from SQLite, verify response content, errors, attachment
    metadata, and metrics remain equivalent.
    """
    attachments = [_make_attachment(spec) for spec in attachment_specs]

    storage = await _create_storage()
    try:
        agent = SuccessAgent(agent_name="roundtrip-agent")
        registry = AgentRegistry()
        registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://roundtrip:9000")

        resource_config = DeploymentResourceConfig(
            cpu_cores=4.0,
            memory_mb=8192.0,
            cost_per_hour=0.50,
        )

        config = RunnerConfig(
            execution_order=[("roundtrip-agent", DeploymentType.LOCAL_DOCKER)],
            delay_between_seconds=0.0,
            timeout_seconds=10.0,
        )
        runner = BenchmarkRunner(
            registry=registry,
            storage=storage,
            config=config,
            deployment_configs={"roundtrip-agent": resource_config},
        )

        benchmark = Benchmark(
            source="cli",
            prompt=prompt,
            attachments=attachments,
        )
        await storage.save_benchmark(benchmark)

        status = await runner.run(benchmark)
        assert status == BenchmarkStatus.COMPLETED

        # Retrieve from SQLite (round-trip)
        executions = await storage.get_executions(benchmark.id)
        assert len(executions) == 1
        ex = executions[0]

        # Verify response content contains prompt
        assert prompt in ex.result.raw_response
        # Verify attachment count is reflected
        if attachments:
            assert f"attachments={len(attachments)}" in ex.result.raw_response

        # Verify no errors
        assert ex.result.errors == []
        assert ex.success is True

        # Verify LLM metrics survived round-trip
        assert ex.llm is not None
        assert ex.llm.model == "model-roundtrip-agent"
        assert ex.llm.prompt_tokens == 10
        assert ex.llm.completion_tokens == 20
        assert ex.llm.total_tokens == 30

        # Verify deployment metrics
        assert ex.deployment.provider == "docker"
        assert ex.deployment.deployment_type == DeploymentType.LOCAL_DOCKER
        assert ex.deployment.cpu_cores == 4.0
        assert ex.deployment.memory_mb == 8192
        assert ex.deployment.estimated_infra_cost_usd is not None
        assert ex.deployment.estimated_infra_cost_usd > 0

        # Verify benchmark attachments survived SQLite round-trip
        saved_benchmark = await storage.get_benchmark(benchmark.id)
        assert saved_benchmark is not None
        assert len(saved_benchmark.attachments) == len(attachments)
        for i, att in enumerate(saved_benchmark.attachments):
            assert att.type == attachments[i].type
            assert att.filename == attachments[i].filename
            assert att.mime_type == attachments[i].mime_type
    finally:
        await storage.close()
