"""Tests for StorageManager initialization and connection management."""

import aiosqlite
import pytest

from benchmark.storage.manager import StorageManager


@pytest.fixture
async def storage(tmp_path):
    """Create a StorageManager with a temporary database."""
    db_path = tmp_path / "test.db"
    manager = StorageManager(db_path)
    await manager.initialize()
    yield manager
    await manager.close()


class TestStorageManagerInitialization:
    """Tests for StorageManager.initialize()."""

    async def test_creates_database_file(self, tmp_path):
        """Database file is created on initialization."""
        db_path = tmp_path / "sub" / "dir" / "test.db"
        manager = StorageManager(db_path)
        await manager.initialize()

        assert db_path.exists()
        await manager.close()

    async def test_enables_wal_mode(self, storage):
        """WAL journal mode is enabled after initialization."""
        conn = await storage.connection()
        cursor = await conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "wal"

    async def test_creates_benchmarks_table(self, storage):
        """Benchmarks table exists with expected columns."""
        conn = await storage.connection()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='benchmarks'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "benchmarks"

    async def test_creates_executions_table(self, storage):
        """Executions table exists with expected columns."""
        conn = await storage.connection()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='executions'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "executions"

    async def test_creates_evaluations_table(self, storage):
        """Evaluations table exists with expected columns."""
        conn = await storage.connection()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evaluations'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "evaluations"

    async def test_creates_indexes(self, storage):
        """All expected indexes are created."""
        conn = await storage.connection()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        rows = await cursor.fetchall()
        index_names = {row[0] for row in rows}

        expected_indexes = {
            "idx_benchmarks_status",
            "idx_benchmarks_created_at",
            "idx_benchmarks_source",
            "idx_executions_benchmark_id",
            "idx_executions_agent",
            "idx_evaluations_benchmark_id",
        }
        assert expected_indexes.issubset(index_names)

    async def test_benchmarks_source_check_constraint(self, storage):
        """Benchmarks table rejects invalid source values."""
        conn = await storage.connection()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO benchmarks (id, source, prompt, created_at) "
                "VALUES ('test1', 'invalid', 'hello', '2024-01-01T00:00:00Z')"
            )

    async def test_benchmarks_status_check_constraint(self, storage):
        """Benchmarks table rejects invalid status values."""
        conn = await storage.connection()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO benchmarks (id, source, prompt, status, created_at) "
                "VALUES ('test1', 'cli', 'hello', 'invalid_status', '2024-01-01T00:00:00Z')"
            )

    async def test_evaluations_rating_check_constraint(self, storage):
        """Evaluations table rejects rating outside 1-5."""
        conn = await storage.connection()
        # First insert a benchmark to satisfy FK
        await conn.execute(
            "INSERT INTO benchmarks (id, source, prompt, created_at) "
            "VALUES ('b1', 'cli', 'hello', '2024-01-01T00:00:00Z')"
        )
        await conn.commit()

        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO evaluations (id, benchmark_id, rating, evaluated_at) "
                "VALUES ('e1', 'b1', 6, '2024-01-01T00:00:00Z')"
            )

    async def test_foreign_keys_enabled(self, storage):
        """Foreign key constraints are enforced."""
        conn = await storage.connection()
        cursor = await conn.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1


class TestStorageManagerConnection:
    """Tests for connection management."""

    async def test_connection_raises_if_not_initialized(self, tmp_path):
        """Accessing connection before initialize() raises RuntimeError."""
        manager = StorageManager(tmp_path / "test.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            await manager.connection()

    async def test_close_sets_connection_to_none(self, tmp_path):
        """After close(), connection is None."""
        manager = StorageManager(tmp_path / "test.db")
        await manager.initialize()
        await manager.close()

        with pytest.raises(RuntimeError, match="not initialized"):
            await manager.connection()

    async def test_context_manager(self, tmp_path):
        """Async context manager initializes and closes correctly."""
        db_path = tmp_path / "ctx.db"
        async with StorageManager(db_path) as manager:
            conn = await manager.connection()
            assert conn is not None
            assert db_path.exists()

        # After exiting context, connection should be closed
        with pytest.raises(RuntimeError, match="not initialized"):
            await manager.connection()

    async def test_idempotent_close(self, tmp_path):
        """Calling close() multiple times does not raise."""
        manager = StorageManager(tmp_path / "test.db")
        await manager.initialize()
        await manager.close()
        await manager.close()  # Should not raise

    async def test_existing_mvp_database_remains_readable(self, tmp_path):
        """Reinitialization keeps existing MVP rows readable without migration loss."""
        db_path = tmp_path / "existing-mvp.db"
        first = StorageManager(db_path)
        await first.initialize()
        conn = await first.connection()
        await conn.execute(
            "INSERT INTO benchmarks (id, source, prompt, created_at) VALUES (?, ?, ?, ?)",
            ("legacy-benchmark", "cli", "legacy prompt", "2024-01-01T00:00:00+00:00"),
        )
        await conn.commit()
        await first.close()

        second = StorageManager(db_path)
        await second.initialize()
        benchmark = await second.get_benchmark("legacy-benchmark")
        assert benchmark is not None
        assert benchmark.prompt == "legacy prompt"

        conn = await second.connection()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('benchmarks', 'executions', 'evaluations')"
        )
        assert {row[0] for row in await cursor.fetchall()} == {
            "benchmarks",
            "executions",
            "evaluations",
        }
        await second.close()
