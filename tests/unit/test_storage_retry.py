"""Tests for Storage Manager retry logic and error handling.

Validates:
- Req 5.6: Exponential backoff retry (50ms start, max 3 attempts) for SQLITE_BUSY
- Req 5.7: Descriptive error after retries exhausted
- Req 5.8: Schema creation failure indicates which table/index failed
- Req 12.3: Transaction rollback on failure preserves committed data
"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmark.models.domain import Benchmark
from benchmark.storage.manager import StorageManager
from benchmark.storage.retry import (
    SchemaCreationError,
    StorageBusyError,
    retry_on_busy,
)

# ---------------------------------------------------------------
# Tests for retry_on_busy decorator
# ---------------------------------------------------------------


class TestRetryOnBusy:
    """Tests for the retry_on_busy decorator."""

    async def test_succeeds_on_first_attempt(self):
        """Function returns immediately when no error occurs."""
        call_count = 0

        @retry_on_busy("test_op")
        async def succeeding_op():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await succeeding_op()
        assert result == "success"
        assert call_count == 1

    async def test_retries_on_sqlite_busy(self):
        """Function retries when SQLITE_BUSY (database is locked) is raised."""
        call_count = 0

        @retry_on_busy("test_op")
        async def busy_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return "success"

        with patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await busy_then_success()

        assert result == "success"
        assert call_count == 3
        # Verify exponential backoff: 50ms, 100ms
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.05)  # 50ms
        mock_sleep.assert_any_call(0.1)  # 100ms

    async def test_raises_storage_busy_error_after_max_attempts(self):
        """StorageBusyError raised after 3 failed attempts."""
        call_count = 0

        @retry_on_busy("save_benchmark")
        async def always_busy():
            nonlocal call_count
            call_count += 1
            raise sqlite3.OperationalError("database is locked")

        with (
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(StorageBusyError) as exc_info,
        ):
            await always_busy()

        assert call_count == 3
        assert exc_info.value.operation == "save_benchmark"
        assert "database contention" in str(exc_info.value)

    async def test_non_busy_errors_propagate_immediately(self):
        """Non-SQLITE_BUSY errors are not retried."""
        call_count = 0

        @retry_on_busy("test_op")
        async def raises_other_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("something else broke")

        with pytest.raises(ValueError, match="something else broke"):
            await raises_other_error()

        assert call_count == 1  # No retry

    async def test_exponential_backoff_timing(self):
        """Delays double each retry: 50ms → 100ms."""

        @retry_on_busy("test_op", initial_delay_ms=50, max_attempts=3)
        async def always_busy():
            raise sqlite3.OperationalError("database is locked")

        with (
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(StorageBusyError),
        ):
            await always_busy()

        # Two sleeps: before attempt 2 and before attempt 3
        assert mock_sleep.call_count == 2
        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [0.05, 0.1]  # 50ms, 100ms

    async def test_custom_initial_delay_and_max_attempts(self):
        """Custom delay and max attempts are respected."""
        call_count = 0

        @retry_on_busy("test_op", initial_delay_ms=100, max_attempts=2)
        async def busy_op():
            nonlocal call_count
            call_count += 1
            raise sqlite3.OperationalError("database is locked")

        with (
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            pytest.raises(StorageBusyError),
        ):
            await busy_op()

        assert call_count == 2
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(0.1)  # 100ms

    async def test_defaults_operation_name_to_function_name(self):
        """Uses function name when operation_name is not provided."""

        @retry_on_busy()
        async def my_cool_operation():
            raise sqlite3.OperationalError("database is locked")

        with (
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(StorageBusyError) as exc_info,
        ):
            await my_cool_operation()

        assert exc_info.value.operation == "my_cool_operation"


# ---------------------------------------------------------------
# Tests for StorageBusyError
# ---------------------------------------------------------------


class TestStorageBusyError:
    """Tests for StorageBusyError exception (Req 5.7)."""

    def test_contains_operation_name(self):
        """Error message includes the operation that failed."""
        cause = sqlite3.OperationalError("database is locked")
        err = StorageBusyError("save_benchmark", cause)
        assert "save_benchmark" in str(err)
        assert err.operation == "save_benchmark"

    def test_contains_cause_description(self):
        """Error message includes the original cause."""
        cause = sqlite3.OperationalError("database is locked")
        err = StorageBusyError("save_execution", cause)
        assert "database is locked" in str(err)
        assert err.cause is cause

    def test_mentions_retry_exhaustion(self):
        """Error message indicates retries were exhausted."""
        cause = sqlite3.OperationalError("database is locked")
        err = StorageBusyError("update_status", cause)
        assert "3 retry attempts" in str(err)
        assert "contention" in str(err)


# ---------------------------------------------------------------
# Tests for SchemaCreationError (Req 5.8)
# ---------------------------------------------------------------


class TestSchemaCreationError:
    """Tests for SchemaCreationError exception."""

    def test_identifies_failed_entity(self):
        """Error message indicates which table/index failed."""
        cause = sqlite3.OperationalError("near syntax error")
        err = SchemaCreationError("benchmarks", cause)
        assert "benchmarks" in str(err)
        assert err.entity == "benchmarks"

    def test_contains_cause(self):
        """Error includes the original cause for debugging."""
        cause = sqlite3.OperationalError("disk full")
        err = SchemaCreationError("idx_benchmarks_status", cause)
        assert "disk full" in str(err)
        assert err.cause is cause


# ---------------------------------------------------------------
# Tests for StorageManager retry integration (Req 5.6, 12.3)
# ---------------------------------------------------------------


class TestStorageManagerRetryIntegration:
    """Tests that StorageManager write methods use retry and rollback."""

    @pytest.fixture
    async def storage(self, tmp_path):
        """Create a StorageManager with a temporary database."""
        db_path = tmp_path / "test.db"
        manager = StorageManager(db_path)
        await manager.initialize()
        yield manager
        await manager.close()

    async def test_save_benchmark_retries_on_busy(self, storage):
        """save_benchmark retries on SQLITE_BUSY before succeeding."""
        benchmark = Benchmark(source="cli", prompt="test prompt")

        # Patch the connection's execute to simulate busy then success
        real_conn = await storage.connection()
        original_execute = real_conn.execute
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Fail on the first INSERT attempt
            if call_count == 1 and "INSERT INTO benchmarks" in str(args[0]):
                raise sqlite3.OperationalError("database is locked")
            return await original_execute(*args, **kwargs)

        with (
            patch.object(real_conn, "execute", side_effect=mock_execute),
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock),
        ):
            await storage.save_benchmark(benchmark)

        # Verify the benchmark was saved on retry
        retrieved = await storage.get_benchmark(benchmark.id)
        assert retrieved is not None
        assert retrieved.prompt == "test prompt"

    async def test_save_benchmark_raises_after_retries_exhausted(self, storage):
        """save_benchmark raises StorageBusyError after 3 failed attempts."""
        benchmark = Benchmark(source="cli", prompt="test prompt")

        real_conn = await storage.connection()

        async def always_busy(*args, **kwargs):
            if "INSERT INTO benchmarks" in str(args[0]):
                raise sqlite3.OperationalError("database is locked")
            # Allow rollback and other operations
            return (
                await real_conn.execute.__wrapped__(*args, **kwargs)
                if hasattr(real_conn.execute, "__wrapped__")
                else MagicMock()
            )

        with (
            patch.object(real_conn, "execute", side_effect=always_busy),
            patch.object(real_conn, "rollback", new_callable=AsyncMock) as mock_rollback,
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(StorageBusyError) as exc_info,
        ):
            await storage.save_benchmark(benchmark)

        assert exc_info.value.operation == "save_benchmark"
        # Rollback should have been called to preserve committed data (Req 12.3)
        mock_rollback.assert_called()

    async def test_rollback_preserves_committed_data(self, storage):
        """On failure, rollback preserves previously committed data (Req 12.3)."""
        # First, save a benchmark successfully
        benchmark1 = Benchmark(source="cli", prompt="first benchmark")
        await storage.save_benchmark(benchmark1)

        # Now try to save another that will fail due to SQLITE_BUSY
        benchmark2 = Benchmark(source="cli", prompt="second benchmark")

        real_conn = await storage.connection()
        original_execute = real_conn.execute

        async def fail_on_second_insert(*args, **kwargs):
            if "INSERT INTO benchmarks" in str(args[0]) and "second benchmark" in str(args):
                raise sqlite3.OperationalError("database is locked")
            return await original_execute(*args, **kwargs)

        with (
            patch.object(real_conn, "execute", side_effect=fail_on_second_insert),
            patch("benchmark.storage.retry.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(StorageBusyError),
        ):
            await storage.save_benchmark(benchmark2)

        # First benchmark should still be retrievable (committed data preserved)
        retrieved = await storage.get_benchmark(benchmark1.id)
        assert retrieved is not None
        assert retrieved.prompt == "first benchmark"


# ---------------------------------------------------------------
# Tests for schema error handling (Req 5.8)
# ---------------------------------------------------------------


class TestSchemaErrorHandling:
    """Tests for schema creation error reporting."""

    async def test_schema_failure_raises_schema_creation_error(self, tmp_path):
        """If schema creation fails, SchemaCreationError is raised with entity name."""
        db_path = tmp_path / "bad_schema.db"
        manager = StorageManager(db_path)

        # Create schema file with invalid SQL that will trigger an error
        bad_schema = (
            "CREATE TABLE IF NOT EXISTS benchmarks (id TEXT PRIMARY KEY);\n"
            "CREATE INDEX idx_bad ON nonexistent_table(col);\n"
        )

        with (
            patch(
                "benchmark.storage.manager.Path.read_text",
                return_value=bad_schema,
            ),
            pytest.raises(SchemaCreationError) as exc_info,
        ):
            await manager.initialize()

        # Should identify the failing entity
        assert exc_info.value.entity != "unknown"
        assert exc_info.value.cause is not None

    async def test_extract_entity_name_for_tables_and_indexes(self):
        """_extract_entity_name correctly identifies table and index names."""
        assert (
            StorageManager._extract_entity_name("CREATE TABLE IF NOT EXISTS benchmarks (id TEXT)")
            == "benchmarks"
        )
        assert (
            StorageManager._extract_entity_name(
                "CREATE INDEX IF NOT EXISTS idx_benchmarks_status ON benchmarks(status)"
            )
            == "idx_benchmarks_status"
        )
        assert (
            StorageManager._extract_entity_name("CREATE TABLE executions (id TEXT)") == "executions"
        )
        assert StorageManager._extract_entity_name("CREATE INDEX idx_foo ON bar(baz)") == "idx_foo"

    async def test_extract_entity_name_unknown_statement(self):
        """Returns 'unknown' for unrecognized statements."""
        assert StorageManager._extract_entity_name("ALTER TABLE foo ADD bar TEXT") == "unknown"
