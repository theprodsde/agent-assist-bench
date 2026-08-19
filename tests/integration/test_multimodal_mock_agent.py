"""Multimodal mock-agent contract tests (Task 16.2).

Extends the local mock-agent flow with fixtures for multimodal contract testing.
Validates that the runner correctly passes attachments through and persists
modality errors using a MockMultimodalAgent that implements AgentAdapter.

Requirements: 3.1, 3.7, 16.2
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from benchmark.agents.base import AgentAdapter, AgentRequest, AgentResponse
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

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# MockMultimodalAgent implementing AgentAdapter protocol
# ---------------------------------------------------------------------------


class MockMultimodalAgent:
    """Mock agent that handles multimodal inputs deterministically.

    - Text-only prompts → echoes prompt in response content
    - Image attachments → includes image filename/mime in response text
    - Audio attachments → returns unsupported_modality:audio error
    - Video attachments → returns unsupported_modality:video error

    The unsupported modalities are configurable via constructor.
    """

    def __init__(
        self,
        *,
        agent_name: str = "mock-multimodal",
        agent_version: str = "1.0.0",
        unsupported_modalities: set[str] | None = None,
    ) -> None:
        self._name = agent_name
        self._version = agent_version
        self._unsupported = unsupported_modalities or {"audio", "video"}

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Process request, handling each attachment by modality."""
        errors: list[str] = []
        response_parts: list[str] = []

        if not request.attachments:
            # Text-only: deterministic response echoing the prompt
            return AgentResponse(
                content=f"mock-response:{request.prompt}",
                errors=[],
            )

        for attachment in request.attachments:
            modality = attachment.type.value

            if modality in self._unsupported:
                errors.append(f"unsupported_modality:{modality}")
            elif modality == "image":
                # Process image: reference filename and mime_type in response
                filename = attachment.filename or "unknown"
                mime = attachment.mime_type or "unknown"
                response_parts.append(f"image_processed:{filename}:{mime}")
            else:
                # Any other supported modality
                response_parts.append(f"processed:{modality}:{attachment.filename}")

        if errors and not response_parts:
            # All attachments unsupported
            return AgentResponse(content="", errors=errors)

        # Mix of supported and unsupported
        content = "|".join(response_parts) if response_parts else ""
        return AgentResponse(content=content, errors=errors)

    async def health_check(self) -> bool:
        """Always healthy."""
        return True


# Verify it satisfies the protocol
assert isinstance(MockMultimodalAgent(), AgentAdapter)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def storage(tmp_path: Path) -> StorageManager:
    """Create a temporary SQLite storage manager."""
    db_path = tmp_path / "test_multimodal.db"
    mgr = StorageManager(db_path=str(db_path))
    await mgr.initialize()
    yield mgr  # type: ignore[misc]
    await mgr.close()


@pytest.fixture
def mock_agent() -> MockMultimodalAgent:
    """Standard mock multimodal agent with audio+video unsupported."""
    return MockMultimodalAgent()


@pytest.fixture
def runner(storage: StorageManager, mock_agent: MockMultimodalAgent) -> BenchmarkRunner:
    """Runner wired with the mock multimodal agent."""
    registry = AgentRegistry()
    registry.register(mock_agent, DeploymentType.LOCAL_DOCKER, "http://mock:9000")
    config = RunnerConfig(
        execution_order=[("mock-multimodal", DeploymentType.LOCAL_DOCKER)],
        delay_between_seconds=0.0,
        timeout_seconds=5.0,
    )
    return BenchmarkRunner(registry=registry, storage=storage, config=config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_text_only_deterministic_response(
    storage: StorageManager, runner: BenchmarkRunner
) -> None:
    """Text-only request → deterministic response echoing prompt."""
    benchmark = Benchmark(source="cli", prompt="Hello multimodal agent")
    await storage.save_benchmark(benchmark)

    status = await runner.run(benchmark)

    assert status == BenchmarkStatus.COMPLETED
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    assert executions[0].success is True
    assert executions[0].result.raw_response == "mock-response:Hello multimodal agent"
    assert executions[0].result.errors == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_image_attachment_processed(storage: StorageManager, runner: BenchmarkRunner) -> None:
    """Image attachment → response includes image filename/mime in response text."""
    benchmark = Benchmark(
        source="cli",
        prompt="Describe this image",
        attachments=[
            Attachment(
                type=InputType.IMAGE,
                filename="photo.png",
                mime_type="image/png",
                size_bytes=1024,
                content_base64="iVBORw0KGgo=",
            )
        ],
    )
    await storage.save_benchmark(benchmark)

    status = await runner.run(benchmark)

    assert status == BenchmarkStatus.COMPLETED
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    assert executions[0].success is True
    assert "photo.png" in executions[0].result.raw_response
    assert "image/png" in executions[0].result.raw_response
    assert "image_processed" in executions[0].result.raw_response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audio_attachment_unsupported(
    storage: StorageManager, runner: BenchmarkRunner
) -> None:
    """Audio attachment → unsupported_modality:audio error."""
    benchmark = Benchmark(
        source="cli",
        prompt="Transcribe this audio",
        attachments=[
            Attachment(
                type=InputType.AUDIO,
                filename="speech.mp3",
                mime_type="audio/mpeg",
                size_bytes=2048,
                content_base64="//uQx",
            )
        ],
    )
    await storage.save_benchmark(benchmark)

    status = await runner.run(benchmark)

    assert status == BenchmarkStatus.FAILED
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    assert executions[0].success is False
    assert "unsupported_modality:audio" in executions[0].result.errors


@pytest.mark.integration
@pytest.mark.asyncio
async def test_video_attachment_unsupported(
    storage: StorageManager, runner: BenchmarkRunner
) -> None:
    """Video attachment → unsupported_modality:video error."""
    benchmark = Benchmark(
        source="cli",
        prompt="Analyze this video",
        attachments=[
            Attachment(
                type=InputType.VIDEO,
                filename="clip.mp4",
                mime_type="video/mp4",
                size_bytes=4096,
                content_base64="AAAAIGZ0eXA=",
            )
        ],
    )
    await storage.save_benchmark(benchmark)

    status = await runner.run(benchmark)

    assert status == BenchmarkStatus.FAILED
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    assert executions[0].success is False
    assert "unsupported_modality:video" in executions[0].result.errors


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_attachments_mixed_support(
    storage: StorageManager, runner: BenchmarkRunner
) -> None:
    """Multiple attachments → processes supported (image), errors for unsupported (video)."""
    benchmark = Benchmark(
        source="cli",
        prompt="Process these files",
        attachments=[
            Attachment(
                type=InputType.IMAGE,
                filename="diagram.jpg",
                mime_type="image/jpeg",
                size_bytes=512,
                content_base64="/9j/4AAQ",
            ),
            Attachment(
                type=InputType.VIDEO,
                filename="demo.mp4",
                mime_type="video/mp4",
                size_bytes=8192,
                content_base64="AAAAIGZ0eXA=",
            ),
        ],
    )
    await storage.save_benchmark(benchmark)

    status = await runner.run(benchmark)

    # Has errors so it's FAILED (single agent with errors)
    assert status == BenchmarkStatus.FAILED
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    ex = executions[0]
    # The image was processed
    assert "image_processed:diagram.jpg:image/jpeg" in ex.result.raw_response
    # The video was rejected
    assert "unsupported_modality:video" in ex.result.errors
    assert ex.success is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configurable_unsupported_modalities(storage: StorageManager, tmp_path: Path) -> None:
    """Agent with only video unsupported allows audio through."""
    agent = MockMultimodalAgent(
        agent_name="audio-ok-agent",
        unsupported_modalities={"video"},
    )
    registry = AgentRegistry()
    registry.register(agent, DeploymentType.LOCAL_DOCKER, "http://mock:9001")
    config = RunnerConfig(
        execution_order=[("audio-ok-agent", DeploymentType.LOCAL_DOCKER)],
        delay_between_seconds=0.0,
        timeout_seconds=5.0,
    )
    runner = BenchmarkRunner(registry=registry, storage=storage, config=config)

    benchmark = Benchmark(
        source="cli",
        prompt="Handle audio",
        attachments=[
            Attachment(
                type=InputType.AUDIO,
                filename="podcast.mp3",
                mime_type="audio/mpeg",
                size_bytes=3000,
                content_base64="//uQx",
            )
        ],
    )
    await storage.save_benchmark(benchmark)

    status = await runner.run(benchmark)

    assert status == BenchmarkStatus.COMPLETED
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    assert executions[0].success is True
    assert "processed:audio:podcast.mp3" in executions[0].result.raw_response


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runner_persists_modality_errors_in_sqlite(
    storage: StorageManager, runner: BenchmarkRunner
) -> None:
    """Verify modality errors survive SQLite round-trip."""
    benchmark = Benchmark(
        source="cli",
        prompt="Process video",
        attachments=[
            Attachment(
                type=InputType.VIDEO,
                filename="recording.mp4",
                mime_type="video/mp4",
                size_bytes=10000,
                content_base64="AAAAIGZ0eXA=",
            )
        ],
    )
    await storage.save_benchmark(benchmark)
    await runner.run(benchmark)

    # Retrieve from storage (SQLite round-trip)
    executions = await storage.get_executions(benchmark.id)
    assert len(executions) == 1
    ex = executions[0]
    assert "unsupported_modality:video" in ex.result.errors
    assert ex.agent_name == "mock-multimodal"
    assert ex.agent_version == "1.0.0"

    # Verify benchmark status persisted
    saved_benchmark = await storage.get_benchmark(benchmark.id)
    assert saved_benchmark is not None
    assert saved_benchmark.status == BenchmarkStatus.FAILED
