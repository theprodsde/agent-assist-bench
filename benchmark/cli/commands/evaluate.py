"""Implementation of the `aab evaluate` command.

Lists benchmarks eligible for evaluation, displays agent responses,
and accepts a human rating with optional preferred agent and notes.

Requirements: 9.3, 6.1-6.5
"""

from __future__ import annotations

import asyncio

import structlog
import typer

from benchmark.cli.wiring import create_context
from benchmark.models.domain import BenchmarkStatus, Evaluation
from benchmark.storage.manager import BenchmarkFilters

logger = structlog.get_logger(__name__)

_EVALUABLE_STATUSES = (BenchmarkStatus.COMPLETED, BenchmarkStatus.PARTIALLY_FAILED)


async def _run_evaluate() -> None:
    """Interactive evaluation flow."""
    ctx = await create_context()
    try:
        # Find benchmarks eligible for evaluation (completed/partially_failed, no eval)
        candidates = []
        for status in _EVALUABLE_STATUSES:
            benchmarks = await ctx.storage.list_benchmarks(
                BenchmarkFilters(status=status, limit=50)
            )
            for b in benchmarks:
                existing = await ctx.storage.get_evaluation(b.id)
                if existing is None:
                    candidates.append(b)

        if not candidates:
            typer.echo("No benchmarks available for evaluation.")
            return

        # Display candidates
        typer.echo("\nBenchmarks available for evaluation:\n")
        for i, b in enumerate(candidates[:20], 1):
            prompt_short = b.prompt[:60] + "..." if len(b.prompt) > 60 else b.prompt
            typer.echo(f"  [{i}] {b.id} — {prompt_short}")

        # Select benchmark
        choice = typer.prompt("\nSelect benchmark number", type=int)
        if choice < 1 or choice > len(candidates[:20]):
            typer.echo("Error: Invalid selection.", err=True)
            raise typer.Exit(code=1)

        selected = candidates[choice - 1]

        # Show agent responses
        executions = await ctx.storage.get_executions(selected.id)
        typer.echo(f"\n{'=' * 60}")
        typer.echo(f"Benchmark: {selected.id}")
        typer.echo(f"Prompt: {selected.prompt[:200]}")
        typer.echo(f"{'=' * 60}\n")

        for ex in executions:
            status_icon = "✓" if ex.success else "✗"
            typer.echo(f"[{status_icon}] {ex.agent_name} ({ex.deployment.deployment_type.value})")
            typer.echo(f"    Latency: {ex.deployment.total_latency_ms:.0f}ms")
            # Do not truncate or repr-format the response: evaluators must be
            # able to compare the exact content returned by each agent.
            typer.echo("    Response:")
            typer.echo(ex.result.raw_response)
            if ex.result.errors:
                typer.echo("    Execution errors:")
                for error in ex.result.errors:
                    typer.echo(f"      - {error}")
            typer.echo("")

        # Collect evaluation
        rating = typer.prompt("Rating (1-5)", type=int)
        if rating < 1 or rating > 5:
            typer.echo("Error: Rating must be between 1 and 5.", err=True)
            raise typer.Exit(code=1)

        agent_names = list({e.agent_name for e in executions})
        preferred = typer.prompt(
            f"Preferred agent ({', '.join(agent_names)}) [optional]",
            default="",
        )
        notes = typer.prompt("Notes [optional]", default="")

        evaluation = Evaluation(
            benchmark_id=selected.id,
            rating=rating,
            preferred_agent=preferred if preferred else None,
            notes=notes if notes else None,
        )

        await ctx.evaluation_service.submit(evaluation)
        typer.echo(f"\nEvaluation submitted: {evaluation.id}")
    finally:
        await ctx.storage.close()


def evaluate_command() -> None:
    """Evaluate benchmark results with a human rating."""
    try:
        asyncio.run(_run_evaluate())
    except typer.Exit:
        raise
    except Exception as exc:
        logger.error("evaluate_command_failed", error=str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
