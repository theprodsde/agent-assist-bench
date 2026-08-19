"""Implementation of the `aab run` command.

Creates a benchmark with source "cli" and dispatches it to the runner.
Prints the benchmark ID to stdout on success.

Requirements: 9.1, 9.5, 9.6, 1.1, 1.2, 1.3
"""

from __future__ import annotations

import asyncio

import structlog
import typer

from benchmark.cli.wiring import create_context
from benchmark.models.domain import Benchmark

logger = structlog.get_logger(__name__)

MAX_PROMPT_LENGTH = 100_000


async def _run_benchmark(prompt: str, tags: list[str]) -> str:
    """Create and execute a benchmark, returning the benchmark ID."""
    ctx = await create_context()
    try:
        benchmark = Benchmark(source="cli", prompt=prompt, tags=tags)
        await ctx.storage.save_benchmark(benchmark)
        logger.info("benchmark_created", benchmark_id=benchmark.id, tags=tags)

        await ctx.runner.run(benchmark)
        return benchmark.id
    finally:
        await ctx.storage.close()


def run_command(prompt: str, tags: list[str] | None = None) -> None:
    """Submit a benchmark request and dispatch for execution.

    Validates prompt length, creates benchmark with source "cli",
    dispatches to runner, and prints benchmark ID to stdout.
    """
    if len(prompt) > MAX_PROMPT_LENGTH:
        typer.echo(
            f"Error: Prompt exceeds maximum length of {MAX_PROMPT_LENGTH:,} characters.",
            err=True,
        )
        raise typer.Exit(code=1)

    if not prompt.strip():
        typer.echo("Error: Prompt must not be empty.", err=True)
        raise typer.Exit(code=1)

    resolved_tags = [t.strip().lower() for t in (tags or []) if t.strip()]

    try:
        benchmark_id = asyncio.run(_run_benchmark(prompt, tags=resolved_tags))
        typer.echo(benchmark_id)
    except Exception as exc:
        logger.error("run_command_failed", error=str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
