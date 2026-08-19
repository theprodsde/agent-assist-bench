"""Implementation of the `aab report` command.

Generates a Markdown comparison report for a configurable time period
(default: last 7 days) and prints it to stdout.

Requirements: 9.4
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
import typer

from benchmark.cli.wiring import create_context

logger = structlog.get_logger(__name__)


async def _generate_report(days: int) -> str:
    """Generate a Markdown report for the specified number of days."""
    ctx = await create_context()
    try:
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=days)

        report = await ctx.report_generator.generate(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        return report
    finally:
        await ctx.storage.close()


def report_command(days: int) -> None:
    """Generate a Markdown comparison report and print to stdout."""
    if days < 1:
        typer.echo("Error: --days must be at least 1.", err=True)
        raise typer.Exit(code=1)

    try:
        output = asyncio.run(_generate_report(days))
        typer.echo(output)
    except typer.Exit:
        raise
    except Exception as exc:
        logger.error("report_command_failed", error=str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
