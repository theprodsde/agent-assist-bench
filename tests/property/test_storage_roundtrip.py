"""Property tests for storage round-trip and query filtering (Task 3.4 + 3.5).

Tests:
- Property 8: Storage Round-Trip
- Property 15: Benchmark Query Filtering
"""

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from benchmark.models.domain import VALID_SOURCES, Benchmark, BenchmarkStatus
from benchmark.storage.manager import BenchmarkFilters, StorageManager


@pytest.fixture
async def storage(tmp_path: Path) -> StorageManager:
    """Create an initialized StorageManager with a temp SQLite database."""
    db_path = tmp_path / "test.db"
    mgr = StorageManager(db_path)
    await mgr.initialize()
    yield mgr  # type: ignore[misc]
    await mgr.close()


# --- Property 8: Storage Round-Trip ---


@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    source=st.sampled_from(list(VALID_SOURCES)),
    prompt=st.text(min_size=1, max_size=1000),
    status=st.sampled_from(list(BenchmarkStatus)),
)
@pytest.mark.asyncio
async def test_storage_round_trip(
    source: str,
    prompt: str,
    status: BenchmarkStatus,
    tmp_path: Path,
) -> None:
    """Saving and retrieving a Benchmark preserves all fields."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "rt.db"
        mgr = StorageManager(db_path)
        await mgr.initialize()
        try:
            benchmark = Benchmark(source=source, prompt=prompt, status=status)
            await mgr.save_benchmark(benchmark)
            retrieved = await mgr.get_benchmark(benchmark.id)

            assert retrieved is not None
            assert retrieved.id == benchmark.id
            assert retrieved.source == benchmark.source
            assert retrieved.prompt == benchmark.prompt
            assert retrieved.status == benchmark.status
            assert retrieved.conversation_id == benchmark.conversation_id
            assert retrieved.execution_count == benchmark.execution_count
            assert retrieved.tags == benchmark.tags
        finally:
            await mgr.close()


# --- Property 15: Benchmark Query Filtering ---


@pytest.mark.asyncio
async def test_filter_by_status(storage: StorageManager) -> None:
    """Filtering by status returns only matching benchmarks."""
    b_pending = Benchmark(source="cli", prompt="pending one", status=BenchmarkStatus.PENDING)
    b_completed = Benchmark(source="api", prompt="completed one", status=BenchmarkStatus.COMPLETED)
    b_failed = Benchmark(source="telegram", prompt="failed one", status=BenchmarkStatus.FAILED)

    await storage.save_benchmark(b_pending)
    await storage.save_benchmark(b_completed)
    await storage.save_benchmark(b_failed)

    results = await storage.list_benchmarks(BenchmarkFilters(status=BenchmarkStatus.COMPLETED))
    assert len(results) == 1
    assert results[0].id == b_completed.id


@pytest.mark.asyncio
async def test_filter_by_source(storage: StorageManager) -> None:
    """Filtering by source returns only matching benchmarks."""
    b1 = Benchmark(source="cli", prompt="cli benchmark")
    b2 = Benchmark(source="api", prompt="api benchmark")
    b3 = Benchmark(source="cli", prompt="another cli")

    await storage.save_benchmark(b1)
    await storage.save_benchmark(b2)
    await storage.save_benchmark(b3)

    results = await storage.list_benchmarks(BenchmarkFilters(source="cli"))
    assert len(results) == 2
    assert all(r.source == "cli" for r in results)


@settings(
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    source=st.sampled_from(list(VALID_SOURCES)),
    status=st.sampled_from(list(BenchmarkStatus)),
)
@pytest.mark.asyncio
async def test_filter_combined(
    source: str,
    status: BenchmarkStatus,
    tmp_path: Path,
) -> None:
    """Combined source and status filters return correct results."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "combined.db"
        mgr = StorageManager(db_path)
        await mgr.initialize()
        try:
            # Create a benchmark matching the filter
            matching = Benchmark(source=source, prompt="match me", status=status)
            await mgr.save_benchmark(matching)

            # Create a non-matching benchmark with different source
            other_source = [s for s in VALID_SOURCES if s != source][0]
            non_matching = Benchmark(source=other_source, prompt="no match", status=status)
            await mgr.save_benchmark(non_matching)

            results = await mgr.list_benchmarks(BenchmarkFilters(source=source, status=status))
            assert all(r.source == source and r.status == status for r in results)
            assert any(r.id == matching.id for r in results)
        finally:
            await mgr.close()


@pytest.mark.asyncio
async def test_pagination(storage: StorageManager) -> None:
    """Pagination limit and offset work correctly."""
    for i in range(5):
        b = Benchmark(source="cli", prompt=f"benchmark {i}")
        await storage.save_benchmark(b)

    page1 = await storage.list_benchmarks(BenchmarkFilters(limit=2, offset=0))
    page2 = await storage.list_benchmarks(BenchmarkFilters(limit=2, offset=2))

    assert len(page1) == 2
    assert len(page2) == 2
    # No overlap
    page1_ids = {r.id for r in page1}
    page2_ids = {r.id for r in page2}
    assert page1_ids.isdisjoint(page2_ids)
