"""Implementation of the `aab telegram` command.

Starts a Telegram long-polling bot that:
  1. Receives messages from you (the single configured user)
  2. Strips #tag prefixes to categorise the benchmark
  3. Runs the prompt through all configured agents sequentially
  4. Sends both responses back to your chat

Requirements
------------
- Set BENCH_TELEGRAM_BOT_TOKEN in your .env (get it from @BotFather in 2 min)
- Hermes and OpenClaw endpoints must already be running and reachable

Message syntax
--------------
    Just send any text:
        Write a binary search in Python

    Prefix #tag(s) for category reporting:
        #coding Write a binary search in Python
        #research #devops Explain Kubernetes vs Swarm
"""

from __future__ import annotations

import asyncio

import structlog
import typer

from benchmark.cli.wiring import create_context

logger = structlog.get_logger(__name__)


async def _run_bot(token: str) -> None:
    from benchmark.bots.telegram import run_polling

    ctx = await create_context()
    try:
        typer.echo("Telegram bot polling started — send messages to your bot.")
        typer.echo("Press Ctrl-C to stop.\n")
        await run_polling(
            token=token,
            storage=ctx.storage,
            runner=ctx.runner,
        )
    finally:
        await ctx.storage.close()


def telegram_command(token: str) -> None:
    """Start the Telegram polling bot."""
    if not token:
        typer.echo(
            "Error: BENCH_TELEGRAM_BOT_TOKEN is not set.\n"
            "  1. Open Telegram, search @BotFather\n"
            "  2. Send /newbot and follow the prompts\n"
            "  3. Add BENCH_TELEGRAM_BOT_TOKEN=<token> to your .env",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        asyncio.run(_run_bot(token))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("telegram_bot_failed", error=str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
