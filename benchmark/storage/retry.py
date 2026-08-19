"""Async retry logic for SQLite write operations.

Implements exponential backoff retry for SQLITE_BUSY errors, following
the Single Responsibility Principle — retry logic is decoupled from
CRUD operations.
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# Default retry configuration (Req 5.6)
DEFAULT_INITIAL_DELAY_MS: int = 50
DEFAULT_MAX_ATTEMPTS: int = 3


class StorageBusyError(Exception):
    """Raised when a write operation exhausts all retry attempts due to SQLITE_BUSY.

    Contains the operation name and original cause for descriptive error reporting
    (Req 5.7, 12.3).
    """

    def __init__(self, operation: str, cause: Exception) -> None:
        self.operation = operation
        self.cause = cause
        super().__init__(
            f"Storage operation '{operation}' failed after {DEFAULT_MAX_ATTEMPTS} "
            f"retry attempts due to database contention: {cause}"
        )


class SchemaCreationError(Exception):
    """Raised when schema creation fails during initialization (Req 5.8).

    Indicates which table or index could not be created.
    """

    def __init__(self, entity: str, cause: Exception) -> None:
        self.entity = entity
        self.cause = cause
        super().__init__(f"Failed to create schema entity '{entity}': {cause}")


def _is_sqlite_busy(exc: Exception) -> bool:
    """Check if an exception represents an SQLITE_BUSY error."""
    # aiosqlite wraps sqlite3 OperationalError
    import sqlite3

    if isinstance(exc, sqlite3.OperationalError):
        return "database is locked" in str(exc).lower()
    # aiosqlite may wrap it
    if hasattr(exc, "__cause__") and isinstance(exc.__cause__, sqlite3.OperationalError):
        return "database is locked" in str(exc.__cause__).lower()
    # Check the message directly for aiosqlite's OperationalError pass-through
    return "database is locked" in str(exc).lower()


def retry_on_busy(
    operation_name: str | None = None,
    initial_delay_ms: int = DEFAULT_INITIAL_DELAY_MS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, T]]],
    Callable[P, Coroutine[Any, Any, T]],
]:
    """Decorator that retries async functions on SQLITE_BUSY with exponential backoff.

    Args:
        operation_name: Human-readable name for log messages. Defaults to function name.
        initial_delay_ms: Starting delay in milliseconds (doubles each retry). Default 50ms.
        max_attempts: Maximum number of attempts (including first). Default 3.

    Raises:
        StorageBusyError: After all retry attempts are exhausted due to SQLITE_BUSY.

    Example:
        @retry_on_busy("save_benchmark")
        async def save_benchmark(self, benchmark: Benchmark) -> None:
            ...
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        op_name = operation_name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            delay_ms = initial_delay_ms

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if not _is_sqlite_busy(exc):
                        raise

                    if attempt == max_attempts:
                        await logger.awarning(
                            "sqlite_busy_retries_exhausted",
                            operation=op_name,
                            attempts=max_attempts,
                        )
                        raise StorageBusyError(operation=op_name, cause=exc) from exc

                    await logger.ainfo(
                        "sqlite_busy_retry",
                        operation=op_name,
                        attempt=attempt,
                        wait_ms=delay_ms,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay_ms / 1000.0)
                    delay_ms *= 2

            # Unreachable, but satisfies type checker
            raise RuntimeError("Unreachable")  # pragma: no cover

        return wrapper

    return decorator
