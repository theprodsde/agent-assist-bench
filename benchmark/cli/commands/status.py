"""Implementation of the `aab status` command.

Displays the 20 most recent benchmarks with ID, prompt (truncated),
status, execution count, and created timestamp.

Requirements: 9.2
"""

from __future__ import annotations

import asyncio

import structlog
import typer

from benchmark.cli.wiring import create_context
from benchmark.storage.manager import BenchmarkFilters

logger = structlog.get_logger(__name__)

_PROMPT_TRUNCATE = 80
_RECENT_LIMIT = 20


async def _fetch_status() -> str:
    """Fetch and format the 20 most recent benchmarks."""
    ctx = await create_context()
    try:
        benchmarks = await ctx.storage.list_benchmarks(BenchmarkFilters(limit=_RECENT_LIMIT))

        if not benchmarks:
            return "No benchmarks found."

        # Table header
        lines: list[str] = []
        header = f"{'ID':<28} {'Prompt':<80} {'Status':<20} {'Execs':<6} {'Created'}"
        lines.append(header)
        lines.append("-" * len(header))

        for b in benchmarks:
            prompt_display = b.prompt[:_PROMPT_TRUNCATE]
            if len(b.prompt) > _PROMPT_TRUNCATE:
                prompt_display = prompt_display[: _PROMPT_TRUNCATE - 3] + "..."
            created = b.created_at.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(
                f"{b.id:<28} {prompt_display:<80} {b.status.value:<20} "
                f"{b.execution_count:<6} {created}"
            )

        return "\n".join(lines)
    finally:
        await ctx.storage.close()


def status_command() -> None:
    """Display the status of the 20 most recently created benchmarks."""
    try:
        output = asyncio.run(_fetch_status())
        typer.echo(output)
    except Exception as exc:
        logger.error("status_command_failed", error=str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
