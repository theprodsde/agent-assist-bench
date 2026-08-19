"""Daily data exporter producing JSONL and CSV snapshots."""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog

from benchmark.models.domain import Benchmark, Evaluation, Execution, ExportManifest

if TYPE_CHECKING:
    from benchmark.storage.manager import StorageManager

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

BENCHMARK_COLUMNS = ["id", "source", "prompt", "status", "created_at", "completed_at"]
EXECUTION_COLUMNS = [
    "id",
    "benchmark_id",
    "agent_name",
    "deployment_provider",
    "deployment_type",
    "cpu_cores",
    "memory_mb",
    "cold_start_ms",
    "total_latency_ms",
    "network_latency_ms",
    "estimated_infra_cost_usd",
    "llm_model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "api_latency_ms",
    "estimated_cost_usd",
    "raw_response",
    "errors",
    "logs",
    "tool_calls",
    "browser_actions",
    "success",
]
EVALUATION_COLUMNS = ["id", "benchmark_id", "rating", "preferred_agent", "notes"]


class ExportError(Exception):
    """Raised when a daily export fails due to storage or file system errors."""


class DailyExporter:
    """Exports daily benchmark data as JSONL and CSV snapshots."""

    def __init__(self, storage: StorageManager, export_dir: Path = Path("storage/exports")) -> None:
        self._storage = storage
        self._export_dir = export_dir

    async def export_day(self, date: str) -> ExportManifest:
        """Export all benchmark data for a given date.

        Raises:
            ExportError: If storage read or file system write fails.
                         Any partial files are cleaned up before raising.
        """
        logger.info("export.start", date=date)
        date_dir = self._export_dir / date
        date_dir.mkdir(parents=True, exist_ok=True)

        try:
            benchmarks = await self._storage.get_benchmarks_for_date(date)
            executions: list[Execution] = []
            evaluations: list[Evaluation] = []
            for bid in [b.id for b in benchmarks]:
                executions.extend(await self._storage.get_executions(bid))
                ev = await self._storage.get_evaluation(bid)
                if ev:
                    evaluations.append(ev)
        except Exception as exc:
            logger.error("export.storage_read_error", date=date, error=str(exc))
            self._cleanup(date_dir)
            raise ExportError(f"Storage read error during export for {date}: {exc}") from exc

        try:
            files: list[str] = []
            jsonl_path = date_dir / f"benchmarks_{date}.jsonl"
            self._write_jsonl(jsonl_path, benchmarks, executions, evaluations)
            files.append(str(jsonl_path))

            for name, items, cols, row_fn in [
                ("benchmarks", benchmarks, BENCHMARK_COLUMNS, self._benchmark_row),
                ("executions", executions, EXECUTION_COLUMNS, self._execution_row),
                ("evaluations", evaluations, EVALUATION_COLUMNS, self._evaluation_row),
            ]:
                csv_path = date_dir / f"{name}_{date}.csv"
                self._write_csv(
                    csv_path,
                    cast("list[Any]", items),
                    cols,
                    cast("Callable[[Any], list[Any]]", row_fn),
                )
                files.append(str(csv_path))
        except ExportError:
            raise
        except Exception as exc:
            logger.error("export.write_error", date=date, error=str(exc))
            self._cleanup(date_dir)
            raise ExportError(f"File write error during export for {date}: {exc}") from exc

        manifest = ExportManifest(
            date=date,
            exported_at=datetime.now(UTC),
            files=files,
            benchmark_count=len(benchmarks),
            execution_count=len(executions),
            evaluation_count=len(evaluations),
        )
        logger.info(
            "export.complete",
            date=date,
            file_count=len(files),
            benchmarks=len(benchmarks),
            executions=len(executions),
            evaluations=len(evaluations),
        )
        return manifest

    def _cleanup(self, date_dir: Path) -> None:
        """Remove partial export directory and its contents."""
        if date_dir.exists():
            shutil.rmtree(date_dir, ignore_errors=True)
            logger.info("export.cleanup", path=str(date_dir))

    def _write_jsonl(
        self,
        path: Path,
        benchmarks: list[Benchmark],
        executions: list[Execution],
        evaluations: list[Evaluation],
    ) -> None:
        """Write JSONL: one JSON object per benchmark. Empty date → zero bytes."""
        with open(path, "w", encoding="utf-8") as f:
            for b in benchmarks:
                record = {
                    "benchmark": b.model_dump(),
                    "executions": [e.model_dump() for e in executions if e.benchmark_id == b.id],
                    "evaluation": next(
                        (ev.model_dump() for ev in evaluations if ev.benchmark_id == b.id),
                        None,
                    ),
                }
                f.write(json.dumps(record, default=str) + "\n")

    def _write_csv(
        self,
        path: Path,
        items: list[Any],
        columns: list[str],
        row_fn: Callable[[Any], list[Any]],
    ) -> None:
        """Write CSV with headers. Empty items → headers only."""
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for item in items:
                writer.writerow(row_fn(item))

    @staticmethod
    def _benchmark_row(b: Benchmark) -> list[Any]:
        return [
            b.id,
            b.source,
            b.prompt,
            str(b.status),
            str(b.created_at),
            str(b.completed_at) if b.completed_at else "",
        ]

    @staticmethod
    def _execution_row(e: Execution) -> list[Any]:
        """Return a lossless, flat representation of an execution.

        JSON encoding is used for list-valued fields so CSV consumers can
        reconstruct errors and auxiliary result data without relying on Python
        repr formatting.  Response text is passed directly to csv.writer,
        which preserves newlines, Unicode, and trailing spaces in the quoted
        field.
        """
        llm = e.llm
        deployment = e.deployment
        return [
            e.id,
            e.benchmark_id,
            e.agent_name,
            deployment.provider,
            str(deployment.deployment_type),
            deployment.cpu_cores,
            deployment.memory_mb,
            deployment.cold_start_ms,
            deployment.total_latency_ms,
            deployment.network_latency_ms,
            deployment.estimated_infra_cost_usd,
            llm.model if llm else "",
            llm.prompt_tokens if llm else "",
            llm.completion_tokens if llm else "",
            llm.total_tokens if llm else "",
            llm.api_latency_ms if llm else "",
            llm.estimated_cost_usd if llm else "",
            e.result.raw_response,
            json.dumps(e.result.errors, ensure_ascii=False),
            json.dumps(e.result.logs, ensure_ascii=False),
            json.dumps(e.result.tool_calls, ensure_ascii=False),
            json.dumps(e.result.browser_actions, ensure_ascii=False),
            e.success,
        ]

    @staticmethod
    def _evaluation_row(ev: Evaluation) -> list[Any]:
        return [ev.id, ev.benchmark_id, ev.rating, ev.preferred_agent or "", ev.notes or ""]
