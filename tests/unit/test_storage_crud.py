"""Tests for StorageManager CRUD operations.

Covers save/get round-trips, filtering, and pagination for
benchmarks, executions, and evaluations.
"""

from datetime import UTC, datetime

import pytest

from benchmark.models.domain import (
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Evaluation,
    Execution,
    ExecutionResult,
    InputType,
    LLMMetrics,
)
from benchmark.storage.manager import BenchmarkFilters, StorageManager


@pytest.fixture
async def storage(tmp_path):
    """Create a StorageManager with a temporary database."""
    db_path = tmp_path / "test_crud.db"
    manager = StorageManager(db_path)
    await manager.initialize()
    yield manager
    await manager.close()


def _make_benchmark(
    *,
    bench_id: str = "01HTEST000000000000000001",
    source: str = "cli",
    prompt: str = "Test prompt",
    status: BenchmarkStatus = BenchmarkStatus.PENDING,
    created_at: datetime | None = None,
    tags: list[str] | None = None,
    attachments: list[Attachment] | None = None,
) -> Benchmark:
    """Helper to create a Benchmark with sensible defaults."""
    return Benchmark(
        id=bench_id,
        source=source,
        prompt=prompt,
        status=status,
        created_at=created_at or datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        tags=tags or [],
        attachments=attachments or [],
    )


def _make_execution(
    *,
    exec_id: str = "01HTEST000000000000000010",
    benchmark_id: str = "01HTEST000000000000000001",
    agent_name: str = "hermes",
    agent_version: str = "1.0.0",
    success: bool = True,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> Execution:
    """Helper to create an Execution with sensible defaults."""
    started = started_at or datetime(2024, 6, 15, 12, 0, 1, tzinfo=UTC)
    completed = completed_at or datetime(2024, 6, 15, 12, 0, 5, tzinfo=UTC)
    return Execution(
        id=exec_id,
        benchmark_id=benchmark_id,
        agent_name=agent_name,
        agent_version=agent_version,
        deployment=DeploymentMetrics(
            provider="local",
            deployment_type=DeploymentType.LOCAL_DOCKER,
            cpu_cores=4.0,
            memory_mb=8192,
            cold_start_ms=150.0,
            total_latency_ms=3200.0,
            network_latency_ms=10.5,
        ),
        llm=LLMMetrics(
            model="gpt-4",
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
            api_latency_ms=2800.0,
            estimated_cost_usd=0.05,
        ),
        result=ExecutionResult(
            raw_response="Hello, world!",
            tool_calls=[{"name": "search", "args": {"q": "test"}}],
            browser_actions=[{"action": "click", "selector": "#btn"}],
            errors=["warning: timeout approaching"],
            logs=["Starting execution", "Done"],
        ),
        started_at=started,
        completed_at=completed,
        success=success,
    )


def _make_evaluation(
    *,
    eval_id: str = "01HTEST000000000000000020",
    benchmark_id: str = "01HTEST000000000000000001",
    rating: int = 4,
) -> Evaluation:
    """Helper to create an Evaluation with sensible defaults."""
    return Evaluation(
        id=eval_id,
        benchmark_id=benchmark_id,
        rating=rating,
        preferred_agent="hermes",
        preferred_deployment=DeploymentType.LOCAL_DOCKER,
        notes="Good response quality",
        evaluator="tester",
        evaluated_at=datetime(2024, 6, 15, 14, 0, 0, tzinfo=UTC),
    )


# ======================================================================
# Benchmark CRUD tests
# ======================================================================


class TestBenchmarkCrud:
    """Tests for save_benchmark, get_benchmark, update_status."""

    async def test_save_and_get_benchmark_roundtrip(self, storage):
        """A saved benchmark can be retrieved with all fields intact."""
        bm = _make_benchmark(tags=["performance", "llm"])
        await storage.save_benchmark(bm)

        result = await storage.get_benchmark(bm.id)
        assert result is not None
        assert result.id == bm.id
        assert result.source == "cli"
        assert result.prompt == "Test prompt"
        assert result.status == BenchmarkStatus.PENDING
        assert result.tags == ["performance", "llm"]
        assert result.execution_count == 0
        assert result.conversation_id is None

    async def test_save_benchmark_with_attachments(self, storage):
        """Attachments are serialized/deserialized as JSON correctly."""
        attachment = Attachment(
            type=InputType.URL,
            url="https://example.com/doc.pdf",
            mime_type="application/pdf",
        )
        bm = _make_benchmark(attachments=[attachment])
        await storage.save_benchmark(bm)

        result = await storage.get_benchmark(bm.id)
        assert result is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].type == InputType.URL
        assert result.attachments[0].url == "https://example.com/doc.pdf"

    async def test_get_benchmark_not_found(self, storage):
        """Getting a non-existent benchmark returns None."""
        result = await storage.get_benchmark("nonexistent_id")
        assert result is None

    async def test_update_status_to_running(self, storage):
        """Updating status to RUNNING does not set completed_at."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        await storage.update_status(bm.id, BenchmarkStatus.RUNNING)

        result = await storage.get_benchmark(bm.id)
        assert result is not None
        assert result.status == BenchmarkStatus.RUNNING
        assert result.completed_at is None

    async def test_update_status_to_completed_sets_completed_at(self, storage):
        """Updating to a terminal status sets completed_at."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        await storage.update_status(bm.id, BenchmarkStatus.COMPLETED)

        result = await storage.get_benchmark(bm.id)
        assert result is not None
        assert result.status == BenchmarkStatus.COMPLETED
        assert result.completed_at is not None

    async def test_get_benchmarks_for_date(self, storage):
        """get_benchmarks_for_date returns only benchmarks for that date."""
        bm1 = _make_benchmark(
            bench_id="01HTEST000000000000000001",
            created_at=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
        )
        bm2 = _make_benchmark(
            bench_id="01HTEST000000000000000002",
            created_at=datetime(2024, 6, 16, 8, 0, 0, tzinfo=UTC),
        )
        await storage.save_benchmark(bm1)
        await storage.save_benchmark(bm2)

        results = await storage.get_benchmarks_for_date("2024-06-15")
        assert len(results) == 1
        assert results[0].id == bm1.id

    async def test_get_benchmarks_for_date_empty(self, storage):
        """get_benchmarks_for_date returns empty list for date with no data."""
        results = await storage.get_benchmarks_for_date("2024-01-01")
        assert results == []


# ======================================================================
# Execution CRUD tests
# ======================================================================


class TestExecutionCrud:
    """Tests for save_execution and get_executions."""

    async def test_save_and_get_execution_roundtrip(self, storage):
        """A saved execution can be retrieved with all fields intact."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ex = _make_execution()
        await storage.save_execution(ex)

        results = await storage.get_executions(bm.id)
        assert len(results) == 1
        result = results[0]
        assert result.id == ex.id
        assert result.benchmark_id == bm.id
        assert result.agent_name == "hermes"
        assert result.agent_version == "1.0.0"
        assert result.success is True

    async def test_execution_deployment_metrics_roundtrip(self, storage):
        """Deployment metrics are correctly flattened and reconstructed."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ex = _make_execution()
        await storage.save_execution(ex)

        results = await storage.get_executions(bm.id)
        dep = results[0].deployment
        assert dep.provider == "local"
        assert dep.deployment_type == DeploymentType.LOCAL_DOCKER
        assert dep.cpu_cores == 4.0
        assert dep.memory_mb == 8192
        assert dep.cold_start_ms == 150.0
        assert dep.total_latency_ms == 3200.0
        assert dep.network_latency_ms == 10.5

    async def test_execution_llm_metrics_roundtrip(self, storage):
        """LLM metrics are correctly persisted and reconstructed."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ex = _make_execution()
        await storage.save_execution(ex)

        results = await storage.get_executions(bm.id)
        llm = results[0].llm
        assert llm is not None
        assert llm.model == "gpt-4"
        assert llm.prompt_tokens == 500
        assert llm.completion_tokens == 200
        assert llm.total_tokens == 700
        assert llm.estimated_cost_usd == 0.05

    async def test_execution_without_llm_metrics(self, storage):
        """Execution with no LLM metrics has llm=None after retrieval."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ex = Execution(
            id="01HTEST000000000000000011",
            benchmark_id=bm.id,
            agent_name="openclaw",
            agent_version="2.0.0",
            deployment=DeploymentMetrics(
                provider="aws",
                deployment_type=DeploymentType.MANAGED_CONTAINER,
                total_latency_ms=1500.0,
            ),
            llm=None,
            result=ExecutionResult(raw_response="No LLM used"),
            started_at=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
            completed_at=datetime(2024, 6, 15, 12, 0, 2, tzinfo=UTC),
            success=True,
        )
        await storage.save_execution(ex)

        results = await storage.get_executions(bm.id)
        assert len(results) == 1
        assert results[0].llm is None

    async def test_execution_json_fields_roundtrip(self, storage):
        """tool_calls, browser_actions, errors, logs survive serialization."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ex = _make_execution()
        await storage.save_execution(ex)

        results = await storage.get_executions(bm.id)
        result = results[0].result
        assert result.tool_calls == [{"name": "search", "args": {"q": "test"}}]
        assert result.browser_actions == [{"action": "click", "selector": "#btn"}]
        assert result.errors == ["warning: timeout approaching"]
        assert result.logs == ["Starting execution", "Done"]

    async def test_get_executions_empty(self, storage):
        """get_executions returns empty list for benchmark with no executions."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        results = await storage.get_executions(bm.id)
        assert results == []

    async def test_multiple_executions_ordered(self, storage):
        """Multiple executions are returned in started_at order."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ex1 = _make_execution(
            exec_id="01HTEST000000000000000010",
            started_at=datetime(2024, 6, 15, 12, 0, 1, tzinfo=UTC),
            completed_at=datetime(2024, 6, 15, 12, 0, 5, tzinfo=UTC),
        )
        ex2 = _make_execution(
            exec_id="01HTEST000000000000000011",
            agent_name="openclaw",
            started_at=datetime(2024, 6, 15, 12, 0, 10, tzinfo=UTC),
            completed_at=datetime(2024, 6, 15, 12, 0, 14, tzinfo=UTC),
        )
        await storage.save_execution(ex1)
        await storage.save_execution(ex2)

        results = await storage.get_executions(bm.id)
        assert len(results) == 2
        assert results[0].id == ex1.id
        assert results[1].id == ex2.id


# ======================================================================
# Evaluation CRUD tests
# ======================================================================


class TestEvaluationCrud:
    """Tests for save_evaluation and get_evaluation."""

    async def test_save_and_get_evaluation_roundtrip(self, storage):
        """A saved evaluation can be retrieved with all fields intact."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ev = _make_evaluation()
        await storage.save_evaluation(ev)

        result = await storage.get_evaluation(bm.id)
        assert result is not None
        assert result.id == ev.id
        assert result.benchmark_id == bm.id
        assert result.rating == 4
        assert result.preferred_agent == "hermes"
        assert result.preferred_deployment == DeploymentType.LOCAL_DOCKER
        assert result.notes == "Good response quality"
        assert result.evaluator == "tester"

    async def test_get_evaluation_not_found(self, storage):
        """get_evaluation returns None when no evaluation exists."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        result = await storage.get_evaluation(bm.id)
        assert result is None

    async def test_evaluation_without_optional_fields(self, storage):
        """Evaluation with None optional fields round-trips correctly."""
        bm = _make_benchmark()
        await storage.save_benchmark(bm)

        ev = Evaluation(
            id="01HTEST000000000000000021",
            benchmark_id=bm.id,
            rating=3,
            preferred_agent=None,
            preferred_deployment=None,
            notes=None,
            evaluator=None,
            evaluated_at=datetime(2024, 6, 15, 14, 0, 0, tzinfo=UTC),
        )
        await storage.save_evaluation(ev)

        result = await storage.get_evaluation(bm.id)
        assert result is not None
        assert result.preferred_agent is None
        assert result.preferred_deployment is None
        assert result.notes is None
        assert result.evaluator is None


# ======================================================================
# Filtering and Pagination tests
# ======================================================================


class TestListBenchmarksFiltering:
    """Tests for list_benchmarks filtering and pagination."""

    async def _seed_benchmarks(self, storage):
        """Insert multiple benchmarks for filtering tests."""
        benchmarks = [
            _make_benchmark(
                bench_id="01HTEST000000000000000001",
                source="cli",
                status=BenchmarkStatus.COMPLETED,
                created_at=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            ),
            _make_benchmark(
                bench_id="01HTEST000000000000000002",
                source="api",
                status=BenchmarkStatus.PENDING,
                created_at=datetime(2024, 6, 15, 11, 0, 0, tzinfo=UTC),
            ),
            _make_benchmark(
                bench_id="01HTEST000000000000000003",
                source="telegram",
                status=BenchmarkStatus.COMPLETED,
                created_at=datetime(2024, 6, 16, 9, 0, 0, tzinfo=UTC),
            ),
            _make_benchmark(
                bench_id="01HTEST000000000000000004",
                source="cli",
                status=BenchmarkStatus.FAILED,
                created_at=datetime(2024, 6, 17, 8, 0, 0, tzinfo=UTC),
            ),
            _make_benchmark(
                bench_id="01HTEST000000000000000005",
                source="discord",
                status=BenchmarkStatus.RUNNING,
                created_at=datetime(2024, 6, 18, 7, 0, 0, tzinfo=UTC),
            ),
        ]
        for bm in benchmarks:
            await storage.save_benchmark(bm)
        return benchmarks

    async def test_list_all_no_filters(self, storage):
        """No filters returns all benchmarks."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(BenchmarkFilters())
        assert len(results) == 5

    async def test_filter_by_status(self, storage):
        """Filtering by status returns only matching benchmarks."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(BenchmarkFilters(status=BenchmarkStatus.COMPLETED))
        assert len(results) == 2
        assert all(r.status == BenchmarkStatus.COMPLETED for r in results)

    async def test_filter_by_source(self, storage):
        """Filtering by source returns only matching benchmarks."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(BenchmarkFilters(source="cli"))
        assert len(results) == 2
        assert all(r.source == "cli" for r in results)

    async def test_filter_by_date_range(self, storage):
        """Filtering by date range returns benchmarks within range."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(
            BenchmarkFilters(
                date_from="2024-06-16",
                date_to="2024-06-17T23:59:59",
            )
        )
        assert len(results) == 2
        ids = {r.id for r in results}
        assert "01HTEST000000000000000003" in ids
        assert "01HTEST000000000000000004" in ids

    async def test_filter_combined(self, storage):
        """Combining multiple filters narrows results."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(
            BenchmarkFilters(
                status=BenchmarkStatus.COMPLETED,
                source="cli",
            )
        )
        assert len(results) == 1
        assert results[0].id == "01HTEST000000000000000001"

    async def test_pagination_limit(self, storage):
        """Limit restricts the number of results."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(BenchmarkFilters(limit=2))
        assert len(results) == 2

    async def test_pagination_offset(self, storage):
        """Offset skips the first N results."""
        await self._seed_benchmarks(storage)

        all_results = await storage.list_benchmarks(BenchmarkFilters())
        offset_results = await storage.list_benchmarks(BenchmarkFilters(offset=2))
        assert len(offset_results) == 3
        # Results are ordered by created_at DESC, so offset=2 skips 2 newest
        assert offset_results[0].id == all_results[2].id

    async def test_pagination_limit_and_offset(self, storage):
        """Limit and offset work together for pagination."""
        await self._seed_benchmarks(storage)

        page1 = await storage.list_benchmarks(BenchmarkFilters(limit=2, offset=0))
        page2 = await storage.list_benchmarks(BenchmarkFilters(limit=2, offset=2))
        page3 = await storage.list_benchmarks(BenchmarkFilters(limit=2, offset=4))

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
        # No overlap
        all_ids = [r.id for r in page1 + page2 + page3]
        assert len(set(all_ids)) == 5

    async def test_limit_above_200_is_preserved(self, storage):
        """Limit > 200 is no longer capped — large periods need more rows."""
        filters = BenchmarkFilters(limit=500)
        assert filters.limit == 500

    async def test_limit_zero_means_unlimited(self, storage):
        """limit=0 is the sentinel for 'fetch all rows' (maps to SQL LIMIT -1)."""
        filters = BenchmarkFilters(limit=0)
        assert filters.limit == 0

    async def test_negative_limit_clamped_to_zero(self, storage):
        """Negative limit is clamped to 0 (unlimited)."""
        filters = BenchmarkFilters(limit=-5)
        assert filters.limit == 0

    async def test_default_limit_is_50(self, storage):
        """Default limit is 50."""
        filters = BenchmarkFilters()
        assert filters.limit == 50

    async def test_results_ordered_by_created_at_desc(self, storage):
        """Results are ordered newest first."""
        await self._seed_benchmarks(storage)

        results = await storage.list_benchmarks(BenchmarkFilters())
        created_ats = [r.created_at for r in results]
        assert created_ats == sorted(created_ats, reverse=True)

    async def test_attachment_content_and_legacy_metadata_roundtrip(self, storage):
        """Bytes, base64, URLs, and connector metadata survive SQLite JSON storage."""
        byte_content = b"\x00PNG\xff\x10"
        attachments = [
            Attachment(
                type=InputType.IMAGE,
                filename="diagram.png",
                mime_type="image/png",
                size_bytes=len(byte_content),
                content_bytes=byte_content,
                connector_file_id="telegram-file-123",
                metadata={
                    "__aab_codec__": "bytes-v1",
                    "value": "not actually encoded",
                },
            ),
            Attachment(
                type=InputType.AUDIO,
                filename="note.mp3",
                mime_type="audio/mpeg",
                size_bytes=4,
                content_base64="AP8QIA==",
            ),
            Attachment(
                type=InputType.URL,
                filename="clip.mp4",
                url="https://cdn.example/clip.mp4",
                mime_type="video/mp4",
                size_bytes=2048,
            ),
            Attachment(
                type=InputType.TEXT,
                content="legacy connector content",
                filename="legacy.txt",
            ),
        ]
        benchmark = _make_benchmark(attachments=attachments)
        await storage.save_benchmark(benchmark)

        result = await storage.get_benchmark(benchmark.id)

        assert result is not None
        assert result.attachments[0].content_bytes == byte_content
        assert result.attachments[0].model_extra == {
            "connector_file_id": "telegram-file-123",
            "metadata": {
                "__aab_codec__": "bytes-v1",
                "value": "not actually encoded",
            },
        }
        assert result.attachments[1].content_base64 == "AP8QIA=="
        assert result.attachments[2].url == "https://cdn.example/clip.mp4"
        assert result.attachments[2].filename == "clip.mp4"
        assert result.attachments[2].mime_type == "video/mp4"
        assert result.attachments[2].size_bytes == 2048
        assert result.attachments[3].model_extra == {"content": "legacy connector content"}

    async def test_attachment_bytes_roundtrip_is_binary_exact(self, storage):
        """Arbitrary non-UTF-8 attachment bytes round-trip byte-for-byte."""
        content = bytes(range(256))
        benchmark = _make_benchmark(
            attachments=[
                Attachment(
                    type=InputType.DOCUMENT,
                    filename="binary.dat",
                    mime_type="application/octet-stream",
                    size_bytes=len(content),
                    content_bytes=content,
                )
            ]
        )
        await storage.save_benchmark(benchmark)

        result = await storage.get_benchmark(benchmark.id)

        assert result is not None
        assert result.attachments[0].content_bytes == content
        assert result.attachments[0].size_bytes == len(content)

    async def test_execution_result_and_metrics_roundtrip_exactly(self, storage):
        """Response, errors, logs, tool fields, state, and metrics are unchanged."""
        benchmark = _make_benchmark()
        await storage.save_benchmark(benchmark)
        execution = _make_execution(success=False)
        execution.result.raw_response = "exact response\n  with trailing spaces  "
        execution.result.tool_calls = []
        execution.result.browser_actions = []
        execution.result.errors = ["unsupported_modality:video", "provider warning"]
        execution.result.logs = ["started", "finished"]

        await storage.save_execution(execution)
        results = await storage.get_executions(benchmark.id)

        assert len(results) == 1
        assert results[0].model_dump(mode="python") == execution.model_dump(mode="python")
