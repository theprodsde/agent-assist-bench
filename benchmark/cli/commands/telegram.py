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


async def _run_bot(token: str, allowed_chat_ids: frozenset[str]) -> None:
    from benchmark.bots.telegram import run_polling

    ctx = await create_context()
    try:
        typer.echo("Telegram bot polling started — send messages to your bot.")
        if allowed_chat_ids:
            typer.echo(f"Access restricted to chat IDs: {', '.join(sorted(allowed_chat_ids))}")
        else:
            typer.echo(
                "Warning: BENCH_TELEGRAM_ALLOW_ALL_CHATS is enabled — accepting all chats."
            )
        typer.echo("Press Ctrl-C to stop.\n")
        await run_polling(
            token=token,
            storage=ctx.storage,
            runner=ctx.runner,
            allowed_chat_ids=allowed_chat_ids,
        )
    finally:
        await ctx.storage.close()


def telegram_command(token: str, allowed_chat_ids_str: str, allow_all_chats: bool = False) -> None:
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

    allowed = frozenset(x.strip() for x in allowed_chat_ids_str.split(",") if x.strip())

    if not allowed and not allow_all_chats:
        typer.echo(
            "Error: BENCH_TELEGRAM_ALLOWED_CHAT_IDS is not set.\n"
            "An unrestricted bot lets anyone who finds it run benchmarks on\n"
            "your API quota. To fix:\n"
            "  1. Message @userinfobot in Telegram to get your numeric chat ID\n"
            "  2. Add BENCH_TELEGRAM_ALLOWED_CHAT_IDS=<your-id> to your .env\n"
            "To intentionally run a public bot, set BENCH_TELEGRAM_ALLOW_ALL_CHATS=true.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        asyncio.run(_run_bot(token, allowed))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("telegram_bot_failed", error=str(exc))
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
