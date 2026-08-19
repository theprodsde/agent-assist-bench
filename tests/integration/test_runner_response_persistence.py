"""Integration coverage for adapter responses at the runner/storage boundary."""

from __future__ import annotations

import pytest

from benchmark.agents.base import AgentAdapter, AgentRequest, AgentResponse
from benchmark.agents.openclaw import OpenClawAdapter
from benchmark.agents.registry import AgentRegistry
from benchmark.models.domain import (
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    InputType,
)
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner
from benchmark.storage.manager import StorageManager


class RecordingAgent:
    """Small adapter fixture that records the exact typed request it receives."""

    def __init__(self, name: str, response: AgentResponse) -> None:
        self._name = name
        self._response = response
        self.requests: list[AgentRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "test-1.0"

    async def execute(self, request: AgentRequest) -> AgentResponse:
        self.requests.append(request)
        return self._response

    async def health_check(self) -> bool:
        return True


async def _run_with_storage(
    tmp_path, benchmark: Benchmark, agents: list[tuple[AgentAdapter, DeploymentType]]
):
    """Run a benchmark against real SQLite storage and return saved executions."""
    storage = StorageManager(tmp_path / "runner.db")
    await storage.initialize()
    await storage.save_benchmark(benchmark)

    registry = AgentRegistry()
    execution_order = []
    for agent, deployment in agents:
        registry.register(agent, deployment, f"http://{agent.name}")
        execution_order.append((agent.name, deployment))

    runner = BenchmarkRunner(
        registry,
        storage,
        RunnerConfig(
            execution_order=execution_order,
            delay_between_seconds=0.0,
            timeout_seconds=10.0,
        ),
    )
    status = await runner.run(benchmark)
    executions = await storage.get_executions(benchmark.id)
    await storage.close()
    return status, executions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_modality_error_is_persisted_and_later_agent_runs(tmp_path) -> None:
    """An OpenClaw modality error fails only its execution and preserves later output."""
    benchmark = Benchmark(
        source="cli",
        prompt="Review this clip",
        attachments=[
            Attachment(
                type=InputType.VIDEO,
                filename="clip.mp4",
                mime_type="video/mp4",
                size_bytes=4,
                content_base64="TVA0IQ==",
            )
        ],
    )
    openclaw = OpenClawAdapter(endpoint="http://openclaw.example")
    exact_response = "Later agent response\nwith exact spacing  "
    later = RecordingAgent("later-agent", AgentResponse(content=exact_response))

    status, executions = await _run_with_storage(
        tmp_path,
        benchmark,
        [
            (openclaw, DeploymentType.LOCAL_DOCKER),
            (later, DeploymentType.VIRTUAL_MACHINE),
        ],
    )
    await openclaw.close()

    assert status == BenchmarkStatus.PARTIALLY_FAILED
    assert len(executions) == 2
    first, second = executions
    assert first.success is False
    assert first.result.raw_response == ""
    assert first.result.errors == ["unsupported_modality:video"]
    assert second.success is True
    assert second.result.raw_response == exact_response
    assert second.result.errors == []
    assert len(later.requests) == 1
    assert isinstance(later.requests[0], AgentRequest)
    assert later.requests[0].attachments == benchmark.attachments
    assert later.requests[0].attachments[0].content_base64 == "TVA0IQ=="


@pytest.mark.integration
@pytest.mark.asyncio
async def test_partial_content_and_errors_survive_runner_and_storage(tmp_path) -> None:
    """Content is retained exactly even when an adapter also reports errors."""
    benchmark = Benchmark(source="cli", prompt="Summarize the result")
    partial = "Partial result\nthat must not be discarded\n"
    first = RecordingAgent(
        "partial-agent",
        AgentResponse(
            content=partial,
            errors=["unsupported_modality:audio", "provider_warning"],
        ),
    )
    later_response = "Later successful result"
    later = RecordingAgent("later-agent", AgentResponse(content=later_response))

    status, executions = await _run_with_storage(
        tmp_path,
        benchmark,
        [
            (first, DeploymentType.LOCAL_DOCKER),
            (later, DeploymentType.VIRTUAL_MACHINE),
        ],
    )

    assert status == BenchmarkStatus.PARTIALLY_FAILED
    assert len(executions) == 2
    saved_first, saved_later = executions
    assert saved_first.success is False
    assert saved_first.result.raw_response == partial
    assert saved_first.result.errors == [
        "unsupported_modality:audio",
        "provider_warning",
    ]
    assert saved_later.success is True
    assert saved_later.result.raw_response == later_response
