"""Storage Manager for SQLite persistence layer.

Handles database initialization, connection management, and WAL mode
configuration using aiosqlite for async access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from benchmark.models.domain import (
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Evaluation,
    Execution,
    ExecutionResult,
    LLMMetrics,
)
from benchmark.storage.codec import dumps, loads
from benchmark.storage.retry import SchemaCreationError, retry_on_busy


@dataclass
class BenchmarkFilters:
    """Filtering parameters for list_benchmarks queries.

    Supports filtering by status, date range (created_at), and source.
    Pagination uses limit/offset with a default limit of 50.
    Pass limit=0 to fetch all matching rows (no cap).
    """

    status: BenchmarkStatus | None = None
    date_from: str | None = None  # ISO 8601 date or datetime string
    date_to: str | None = None  # ISO 8601 date or datetime string
    source: str | None = None
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        """Clamp limit to a minimum of 0 (0 = unlimited)."""
        if self.limit < 0:
            self.limit = 0


class StorageManager:
    """Manages SQLite database connections and schema initialization.

    Provides async connection management with WAL mode enabled for
    concurrent read access during writes.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize StorageManager with database path.

        Args:
            db_path: Path to the SQLite database file. Parent directories
                     will be created if they do not exist.
        """
        self._db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> Path:
        """Return the configured database path."""
        return self._db_path

    async def initialize(self) -> None:
        """Create tables, indexes, and enable WAL mode.

        Creates the storage directory if it doesn't exist, opens the
        database connection, enables WAL journal mode, and executes
        the schema DDL to create tables and indexes.

        Raises:
            SchemaCreationError: If a specific table or index cannot be created (Req 5.8).
            RuntimeError: If schema file cannot be read.
        """
        # Ensure the parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection
        self._connection = await aiosqlite.connect(str(self._db_path))

        # Enable WAL mode for concurrent read access during writes (Req 5.5)
        await self._connection.execute("PRAGMA journal_mode=WAL")

        # Enable foreign key enforcement
        await self._connection.execute("PRAGMA foreign_keys=ON")

        # Read schema file
        schema_path = Path(__file__).parent.parent.parent / "storage" / "schema.sql"
        try:
            schema_sql = schema_path.read_text(encoding="utf-8")
        except OSError as exc:
            await self.close()
            raise RuntimeError(f"Failed to read schema file from {schema_path}: {exc}") from exc

        # Execute schema using executescript (handles implicit commits between
        # statements so that CREATE INDEX can reference just-created tables).
        # If it fails, identify the entity from the error message (Req 5.8).
        try:
            await self._connection.executescript(schema_sql)
        except Exception as exc:
            entity_name = self._identify_failed_entity(schema_sql, str(exc))
            await self.close()
            raise SchemaCreationError(entity=entity_name, cause=exc) from exc

        # Migrate existing databases: add columns that may be missing from
        # older schema versions. ALTER TABLE ADD COLUMN is safe to re-run
        # since SQLite will error on duplicate columns — we ignore those.
        await self._apply_migrations()

    async def _apply_migrations(self) -> None:
        """Add columns that may be missing from older schema versions.

        Uses ALTER TABLE ADD COLUMN which is a no-op if the column already
        exists (we catch the 'duplicate column' error and ignore it).
        """
        migrations = [
            "ALTER TABLE executions ADD COLUMN estimated_infra_cost_usd REAL",
        ]
        conn = await self.connection()
        for sql in migrations:
            try:
                await conn.execute(sql)
                await conn.commit()
            except Exception as exc:
                # "duplicate column name" means it already exists — safe to ignore
                if "duplicate column" in str(exc).lower():
                    continue
                # Any other error is unexpected but non-fatal for migrations
                continue

    @staticmethod
    def _identify_failed_entity(schema_sql: str, error_msg: str) -> str:
        """Identify which table or index failed from schema SQL and error message.

        Parses the schema to find entity names and matches against the error.
        """
        entities = StorageManager._extract_all_entity_names(schema_sql)
        error_lower = error_msg.lower()
        for entity in entities:
            if entity.lower() in error_lower:
                return entity
        return entities[-1] if entities else "unknown"

    @staticmethod
    def _extract_all_entity_names(schema_sql: str) -> list[str]:
        """Extract all table and index names from schema SQL."""
        entities: list[str] = []
        statements = [
            stmt.strip()
            for stmt in schema_sql.split(";")
            if stmt.strip() and not stmt.strip().startswith("--")
        ]
        for statement in statements:
            name = StorageManager._extract_entity_name(statement)
            if name != "unknown":
                entities.append(name)
        return entities

    @staticmethod
    def _extract_entity_name(statement: str) -> str:
        """Extract the table or index name from a DDL statement for error reporting."""
        upper = statement.upper()
        # Match CREATE TABLE IF NOT EXISTS <name> or CREATE TABLE <name>
        for keyword in ("CREATE TABLE IF NOT EXISTS", "CREATE TABLE"):
            if keyword in upper:
                rest = statement[upper.index(keyword) + len(keyword) :].strip()
                return rest.split("(")[0].split()[0].strip()
        # Match CREATE INDEX IF NOT EXISTS <name> or CREATE INDEX <name>
        for keyword in ("CREATE INDEX IF NOT EXISTS", "CREATE INDEX"):
            if keyword in upper:
                rest = statement[upper.index(keyword) + len(keyword) :].strip()
                return rest.split()[0].strip()
        return "unknown"

    async def connection(self) -> aiosqlite.Connection:
        """Return the active database connection.

        Returns:
            The aiosqlite connection instance.

        Raises:
            RuntimeError: If the manager has not been initialized.
        """
        if self._connection is None:
            raise RuntimeError("StorageManager not initialized. Call initialize() first.")
        return self._connection

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> StorageManager:
        """Async context manager entry — initializes the database."""
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Async context manager exit — closes the database connection."""
        await self.close()

    # ------------------------------------------------------------------
    # Benchmark CRUD
    # ------------------------------------------------------------------

    @retry_on_busy("save_benchmark")
    async def save_benchmark(self, benchmark: Benchmark) -> None:
        """Persist a Benchmark to the database.

        Serializes attachments and tags as JSON text. Uses ISO 8601 format
        for datetime fields. Retries on SQLITE_BUSY with exponential backoff.

        Raises:
            StorageBusyError: If retries exhausted due to database contention.
            RuntimeError: If not initialized.
        """
        conn = await self.connection()
        try:
            await conn.execute(
                """
                INSERT INTO benchmarks
                    (id, conversation_id, source, prompt, attachments_json,
                     status, tags_json, created_at, completed_at, execution_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    benchmark.id,
                    benchmark.conversation_id,
                    benchmark.source,
                    benchmark.prompt,
                    dumps([a.model_dump(mode="python") for a in benchmark.attachments]),
                    str(benchmark.status),
                    dumps(benchmark.tags),
                    str(benchmark.created_at),
                    str(benchmark.completed_at) if benchmark.completed_at else None,
                    benchmark.execution_count,
                ),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_benchmark(self, benchmark_id: str) -> Benchmark | None:
        """Retrieve a single Benchmark by ID.

        Returns None if not found. Deserializes JSON fields back to
        domain model types.
        """
        conn = await self.connection()
        cursor = await conn.execute("SELECT * FROM benchmarks WHERE id = ?", (benchmark_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_benchmark(row, cursor.description)

    async def list_benchmarks(self, filters: BenchmarkFilters) -> list[Benchmark]:
        """List benchmarks with filtering and pagination.

        Supports filtering by status, date range (created_at), and source.
        Results are ordered by created_at DESC.
        """
        conn = await self.connection()
        query = "SELECT * FROM benchmarks WHERE 1=1"
        params: list[str | int] = []

        if filters.status is not None:
            query += " AND status = ?"
            params.append(str(filters.status))

        if filters.source is not None:
            query += " AND source = ?"
            params.append(filters.source)

        if filters.date_from is not None:
            query += " AND created_at >= ?"
            params.append(filters.date_from)

        if filters.date_to is not None:
            query += " AND created_at <= ?"
            params.append(filters.date_to)

        # limit=0 means "fetch all rows"; SQLite uses -1 for unlimited LIMIT.
        sql_limit = -1 if filters.limit == 0 else filters.limit
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.append(sql_limit)
        params.append(filters.offset)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_benchmark(row, cursor.description) for row in rows]

    @retry_on_busy("update_status")
    async def update_status(self, benchmark_id: str, status: BenchmarkStatus) -> None:
        """Update the status of a benchmark.

        Also sets completed_at if the status is a terminal state
        (completed, partially_failed, failed). Retries on SQLITE_BUSY.

        Raises:
            StorageBusyError: If retries exhausted due to database contention.
        """
        conn = await self.connection()
        try:
            completed_at: str | None = None
            if status in (
                BenchmarkStatus.COMPLETED,
                BenchmarkStatus.PARTIALLY_FAILED,
                BenchmarkStatus.FAILED,
            ):
                completed_at = str(datetime.utcnow())

            if completed_at:
                await conn.execute(
                    "UPDATE benchmarks SET status = ?, completed_at = ? WHERE id = ?",
                    (str(status), completed_at, benchmark_id),
                )
            else:
                await conn.execute(
                    "UPDATE benchmarks SET status = ? WHERE id = ?",
                    (str(status), benchmark_id),
                )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_benchmarks_for_date(self, date: str) -> list[Benchmark]:
        """Get all benchmarks created on a given date (YYYY-MM-DD).

        Used by the Daily Exporter to produce daily snapshots.
        """
        conn = await self.connection()
        # Match date prefix: "2024-01-15" matches "2024-01-15T..."
        cursor = await conn.execute(
            "SELECT * FROM benchmarks WHERE created_at LIKE ? ORDER BY created_at ASC",
            (f"{date}%",),
        )
        rows = await cursor.fetchall()
        return [self._row_to_benchmark(row, cursor.description) for row in rows]

    # ------------------------------------------------------------------
    # Execution CRUD
    # ------------------------------------------------------------------

    @retry_on_busy("save_execution")
    async def save_execution(self, execution: Execution) -> None:
        """Persist an Execution to the database.

        Flattens nested deployment and LLM metrics into columns.
        Serializes tool_calls, browser_actions, errors, and logs as JSON.
        Retries on SQLITE_BUSY with exponential backoff.

        Raises:
            StorageBusyError: If retries exhausted due to database contention.
        """
        conn = await self.connection()
        try:
            await conn.execute(
                """
                INSERT INTO executions
                    (id, benchmark_id, agent_name, agent_version,
                     deployment_provider, deployment_type, cpu_cores, memory_mb,
                     cold_start_ms, total_latency_ms, network_latency_ms,
                     estimated_infra_cost_usd,
                     llm_model, prompt_tokens, completion_tokens, total_tokens,
                     api_latency_ms, estimated_cost_usd,
                     raw_response, tool_calls_json, browser_actions_json,
                     errors_json, logs_json, started_at, completed_at, success)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution.id,
                    execution.benchmark_id,
                    execution.agent_name,
                    execution.agent_version,
                    execution.deployment.provider,
                    str(execution.deployment.deployment_type),
                    execution.deployment.cpu_cores,
                    execution.deployment.memory_mb,
                    execution.deployment.cold_start_ms,
                    execution.deployment.total_latency_ms,
                    execution.deployment.network_latency_ms,
                    execution.deployment.estimated_infra_cost_usd,
                    execution.llm.model if execution.llm else None,
                    execution.llm.prompt_tokens if execution.llm else None,
                    execution.llm.completion_tokens if execution.llm else None,
                    execution.llm.total_tokens if execution.llm else None,
                    execution.llm.api_latency_ms if execution.llm else None,
                    execution.llm.estimated_cost_usd if execution.llm else None,
                    execution.result.raw_response,
                    dumps(execution.result.tool_calls)
                    if execution.result.tool_calls is not None
                    else None,
                    dumps(execution.result.browser_actions)
                    if execution.result.browser_actions is not None
                    else None,
                    dumps(execution.result.errors),
                    dumps(execution.result.logs),
                    str(execution.started_at),
                    str(execution.completed_at),
                    1 if execution.success else 0,
                ),
            )
            await conn.execute(
                "UPDATE benchmarks SET execution_count = execution_count + 1 WHERE id = ?",
                (execution.benchmark_id,),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_executions(self, benchmark_id: str) -> list[Execution]:
        """Retrieve all executions for a given benchmark ID.

        Results are ordered by started_at ASC (execution order).
        """
        conn = await self.connection()
        cursor = await conn.execute(
            "SELECT * FROM executions WHERE benchmark_id = ? ORDER BY started_at ASC",
            (benchmark_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_execution(row, cursor.description) for row in rows]

    # ------------------------------------------------------------------
    # Evaluation CRUD
    # ------------------------------------------------------------------

    @retry_on_busy("save_evaluation")
    async def save_evaluation(self, evaluation: Evaluation) -> None:
        """Persist an Evaluation to the database.

        Retries on SQLITE_BUSY with exponential backoff.

        Raises:
            StorageBusyError: If retries exhausted due to database contention.
        """
        conn = await self.connection()
        try:
            await conn.execute(
                """
                INSERT INTO evaluations
                    (id, benchmark_id, rating, preferred_agent,
                     preferred_deployment, notes, evaluator, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.id,
                    evaluation.benchmark_id,
                    evaluation.rating,
                    evaluation.preferred_agent,
                    str(evaluation.preferred_deployment)
                    if evaluation.preferred_deployment
                    else None,
                    evaluation.notes,
                    evaluation.evaluator,
                    str(evaluation.evaluated_at),
                ),
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def get_evaluation(self, benchmark_id: str) -> Evaluation | None:
        """Retrieve the evaluation for a given benchmark.

        Returns None if no evaluation exists (benchmark_id is UNIQUE in table).
        """
        conn = await self.connection()
        cursor = await conn.execute(
            "SELECT * FROM evaluations WHERE benchmark_id = ?", (benchmark_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_evaluation(row, cursor.description)

    # ------------------------------------------------------------------
    # Private row-to-model mappers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_benchmark(row: Any, description: tuple[Any, ...] | None) -> Benchmark:
        """Convert a database row to a Benchmark domain model."""
        # Column order from schema:
        # id, conversation_id, source, prompt, attachments_json,
        # status, tags_json, created_at, completed_at, execution_count
        cols = [d[0] for d in description] if description else []
        data = dict(zip(cols, row, strict=False))

        attachments_raw = loads(data.get("attachments_json", "[]") or "[]")
        tags_raw = loads(data.get("tags_json", "[]") or "[]")

        return Benchmark(
            id=data["id"],
            conversation_id=data.get("conversation_id"),
            source=data["source"],
            prompt=data["prompt"],
            attachments=[Attachment(**a) for a in attachments_raw],
            status=BenchmarkStatus(data["status"]),
            tags=tags_raw,
            created_at=datetime.fromisoformat(data["created_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            execution_count=data.get("execution_count", 0),
        )

    @staticmethod
    def _row_to_execution(row: Any, description: tuple[Any, ...] | None) -> Execution:
        """Convert a database row to an Execution domain model."""
        cols = [d[0] for d in description] if description else []
        data = dict(zip(cols, row, strict=False))

        deployment = DeploymentMetrics(
            provider=data["deployment_provider"],
            deployment_type=DeploymentType(data["deployment_type"]),
            cpu_cores=data.get("cpu_cores"),
            memory_mb=data.get("memory_mb"),
            cold_start_ms=data.get("cold_start_ms"),
            total_latency_ms=data["total_latency_ms"],
            network_latency_ms=data.get("network_latency_ms"),
            estimated_infra_cost_usd=data.get("estimated_infra_cost_usd"),
        )

        llm: LLMMetrics | None = None
        if data.get("llm_model"):
            llm = LLMMetrics(
                model=data["llm_model"],
                prompt_tokens=data.get("prompt_tokens"),
                completion_tokens=data.get("completion_tokens"),
                total_tokens=data.get("total_tokens"),
                api_latency_ms=data.get("api_latency_ms"),
                estimated_cost_usd=data.get("estimated_cost_usd"),
            )

        tool_calls_raw = data.get("tool_calls_json")
        browser_actions_raw = data.get("browser_actions_json")

        result = ExecutionResult(
            raw_response=data["raw_response"],
            tool_calls=loads(tool_calls_raw) if tool_calls_raw else None,
            browser_actions=loads(browser_actions_raw) if browser_actions_raw else None,
            errors=loads(data.get("errors_json", "[]") or "[]"),
            logs=loads(data.get("logs_json", "[]") or "[]"),
        )

        return Execution(
            id=data["id"],
            benchmark_id=data["benchmark_id"],
            agent_name=data["agent_name"],
            agent_version=data["agent_version"],
            deployment=deployment,
            llm=llm,
            result=result,
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]),
            success=bool(data["success"]),
        )

    @staticmethod
    def _row_to_evaluation(row: Any, description: tuple[Any, ...] | None) -> Evaluation:
        """Convert a database row to an Evaluation domain model."""
        cols = [d[0] for d in description] if description else []
        data = dict(zip(cols, row, strict=False))

        preferred_deployment: DeploymentType | None = None
        if data.get("preferred_deployment"):
            preferred_deployment = DeploymentType(data["preferred_deployment"])

        return Evaluation(
            id=data["id"],
            benchmark_id=data["benchmark_id"],
            rating=data["rating"],
            preferred_agent=data.get("preferred_agent"),
            preferred_deployment=preferred_deployment,
            notes=data.get("notes"),
            evaluator=data.get("evaluator"),
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]),
        )
