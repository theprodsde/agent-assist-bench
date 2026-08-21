"""CLI entry point for AgentAssistBench (aab).

Provides commands to submit benchmarks, check status, evaluate results,
and generate comparison reports. Configuration is loaded from environment
variables (BENCH_ prefix) and .env file.

Requirements: 9.1-9.5, 11.1-11.5, 12.1
"""

from __future__ import annotations

import structlog
import typer

from benchmark.config.settings import Settings

# ---------------------------------------------------------------------------
# Structlog configuration
# ---------------------------------------------------------------------------


def _configure_logging(log_level: str) -> None:
    """Configure structlog with JSON rendering and the specified log level."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.processors.NAME_TO_LEVEL[log_level.lower()]
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ---------------------------------------------------------------------------
# Load settings and configure logging at import time
# ---------------------------------------------------------------------------

settings = Settings()
_configure_logging(settings.log_level)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Typer application
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="aab",
    help="AgentAssistBench — benchmark AI assistants on real-world workflows.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands — delegate to implementation modules (SRP)
# ---------------------------------------------------------------------------


@app.command()
def run(
    prompt: str = typer.Argument(..., help="The prompt to benchmark across agents."),
    tag: list[str] = typer.Option(
        [],
        "--tag",
        "-t",
        help="Category tag for reporting (repeatable: --tag coding --tag research).",
    ),
) -> None:
    """Submit a benchmark request and dispatch for execution."""
    from benchmark.cli.commands.run import run_command

    run_command(prompt, tags=tag)


@app.command()
def status() -> None:
    """Display the status of the most recent benchmarks."""
    from benchmark.cli.commands.status import status_command

    status_command()


@app.command()
def evaluate() -> None:
    """Evaluate benchmark results with a human rating."""
    from benchmark.cli.commands.evaluate import evaluate_command

    evaluate_command()


@app.command()
def report(
    days: int = typer.Option(7, "--days", "-d", help="Number of days to include in the report."),
) -> None:
    """Generate a Markdown comparison report."""
    from benchmark.cli.commands.report import report_command

    report_command(days)


@app.command()
def telegram() -> None:
    """Start the Telegram bot (long-polling).

    Requires BENCH_TELEGRAM_BOT_TOKEN in your .env.
    Send any message to benchmark it; prefix #tag to categorise.

    \\b
    Examples:
      aab telegram
      BENCH_TELEGRAM_BOT_TOKEN=123:ABC aab telegram
    """
    from benchmark.cli.commands.telegram import telegram_command

    telegram_command(
        settings.telegram_bot_token.get_secret_value(),
        settings.telegram_allowed_chat_ids,
    )


# ---------------------------------------------------------------------------
# Allow `python -m benchmark.cli.main` execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
