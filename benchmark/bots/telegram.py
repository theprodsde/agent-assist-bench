"""Telegram long-polling bot for AgentAssistBench.

Connects the existing TelegramConnector to the real Telegram Bot API using
httpx (already a dependency — no additional SDK needed).

Usage
-----
    aab telegram                   # starts polling with BENCH_TELEGRAM_BOT_TOKEN
    BENCH_TELEGRAM_BOT_TOKEN=xxx aab telegram

Message format (send to your bot)
----------------------------------
    Any text is a prompt benchmarked across all configured agents.

    Prefix a word with # to tag the category for reporting:

        #coding Write a binary search in Python
        #research #devops What is a container orchestrator?

    Tags are stripped from the prompt before it is sent to agents.

Limitations
-----------
- Single-process: only one polling loop per bot token.
- Responses are plain text (Telegram MarkdownV2 is not applied because
  agent output may contain characters that would break escaping).
- No conversation threading: every message creates a fresh benchmark.
- Attachments other than images are not supported by the connector.
"""

from __future__ import annotations

import asyncio
import re
import signal
from typing import Any

import httpx
import structlog

from benchmark.connectors.telegram import (
    InMemoryTelegramIdempotency,
    InMemoryTelegramResponseIdempotency,
    TelegramConnector,
    TelegramUpdate,
)

logger = structlog.get_logger(__name__)

_TAG_RE = re.compile(r"#([A-Za-z0-9_-]+)")


def _extract_tags_and_prompt(text: str) -> tuple[list[str], str]:
    """Split '#tag' prefixes from a message and return (tags, clean_prompt).

    Tags may appear anywhere in the message; they are removed before the
    remaining text is used as the benchmark prompt.

        "#coding Write binary search"  →  (["coding"], "Write binary search")
        "Hello #research #devops"      →  (["research", "devops"], "Hello")
    """
    tags = [m.group(1).lower() for m in _TAG_RE.finditer(text)]
    prompt = _TAG_RE.sub("", text).strip()
    return tags, prompt


class TelegramBotApi:
    """Minimal Telegram Bot API client backed by httpx.

    Exposes only the endpoints needed by the polling loop and TelegramConnector:
    getUpdates, sendMessage, and download_file. Attachments are downloaded as
    bytes rather than resolved to URLs: Telegram file URLs embed the bot token,
    and a URL would be persisted to the database and forwarded to every agent
    endpoint — leaking the token to anyone with DB or endpoint access.
    """

    # Telegram's Bot API caps downloadable files at 20 MB.
    MAX_FILE_BYTES = 20 * 1024 * 1024

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_updates(
        self, offset: int | None = None, timeout: int = 25
    ) -> list[dict[str, Any]]:
        """Long-poll for new updates. Returns the raw update list."""
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        resp = await self._client.get(
            f"{self._base}/getUpdates",
            params=params,
            timeout=timeout + 5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", []) if data.get("ok") else []

    async def send_message(self, conversation_id: str, text: str) -> object:
        """Send plain text to a chat. Silently truncates to Telegram's 4096-char limit."""
        if len(text) > 4096:
            text = text[:4090] + "\n…"
        chat_id, _, thread_id = conversation_id.partition(":")
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        resp = await self._client.post(f"{self._base}/sendMessage", json=payload, timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    async def download_file(self, file_id: str) -> bytes | None:
        """Download attachment bytes for a Telegram file_id.

        Returns None when the file cannot be resolved or exceeds
        MAX_FILE_BYTES; the connector then reports the attachment as
        unavailable instead of falling back to a tokenized URL.
        """
        try:
            resp = await self._client.get(
                f"{self._base}/getFile",
                params={"file_id": file_id},
                timeout=10.0,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            file_path = result.get("file_path")
            file_size = result.get("file_size")
            if not file_path:
                return None
            if isinstance(file_size, int) and file_size > self.MAX_FILE_BYTES:
                logger.warning("telegram_file_too_large", file_id=file_id, size=file_size)
                return None
            file_resp = await self._client.get(f"{self._file_base}/{file_path}", timeout=60.0)
            file_resp.raise_for_status()
            content = file_resp.content
            if len(content) > self.MAX_FILE_BYTES:
                logger.warning("telegram_file_too_large", file_id=file_id, size=len(content))
                return None
            return content
        except Exception:
            return None

    async def resolve_file_url(self, file_id: str) -> str | None:
        """Never expose a file URL: Telegram file URLs embed the bot token."""
        return None


class TelegramPollingBot:
    """Long-polling event loop that drives the TelegramConnector.

    Handles graceful shutdown on SIGINT/SIGTERM so aab telegram can be
    stopped with Ctrl-C without leaving the update offset in a broken state.
    """

    def __init__(
        self,
        token: str,
        connector: TelegramConnector,
        api: TelegramBotApi | None = None,
        poll_timeout: int = 25,
        allowed_chat_ids: frozenset[str] | None = None,
    ) -> None:
        self._connector = connector
        self._api = api or TelegramBotApi(token)
        self._poll_timeout = poll_timeout
        self._offset: int | None = None
        self._running = False
        self._allowed_chat_ids: frozenset[str] = allowed_chat_ids or frozenset()

    async def run(self) -> None:
        """Block until SIGINT or SIGTERM; process each update in order."""
        self._running = True
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop)

        logger.info("telegram_bot_polling_started", poll_timeout=self._poll_timeout)
        try:
            while self._running:
                try:
                    updates = await self._api.get_updates(
                        offset=self._offset, timeout=self._poll_timeout
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    await asyncio.sleep(2)
                    continue
                except httpx.HTTPStatusError as exc:
                    logger.error("telegram_api_error", status=exc.response.status_code)
                    await asyncio.sleep(5)
                    continue

                for raw in updates:
                    update_id = raw.get("update_id", 0)
                    await self._handle(raw)
                    self._offset = update_id + 1
        finally:
            await self._api.close()
            logger.info("telegram_bot_polling_stopped")

    def _stop(self) -> None:
        self._running = False

    async def _handle(self, raw: dict[str, Any]) -> None:
        """Process one raw update dict through the connector."""
        try:
            update = TelegramUpdate.model_validate(raw)
        except Exception:
            logger.warning("telegram_update_parse_failed", update_id=raw.get("update_id"))
            return

        message = update.message
        if message is None:
            return

        if self._allowed_chat_ids:
            chat_id = str(message.chat.id) if message.chat is not None else None
            if chat_id not in self._allowed_chat_ids:
                logger.warning(
                    "telegram_update_unauthorized",
                    update_id=str(update.update_id),
                    chat_id=chat_id,
                )
                return

        # Inject tags extracted from #hashtags before handing to connector.
        # The connector receives the clean prompt; tags are stored on the Benchmark.
        text = message.text or message.caption or ""
        tags, clean = _extract_tags_and_prompt(text)
        if clean:
            message.text = clean
            if message.caption:
                message.caption = clean
        update._tags = tags  # type: ignore[attr-defined]  # carried through _to_benchmark monkey-patch below

        result = await self._connector.handle_update(update)

        if result.error and not result.duplicate:
            logger.warning(
                "telegram_update_error",
                code=result.error.code,
                update_id=str(update.update_id),
            )


class _TaggingConnector(TelegramConnector):
    """TelegramConnector subclass that propagates #tags extracted by the bot."""

    async def _to_benchmark(self, update: Any) -> Any:
        bench = await super()._to_benchmark(update)
        tags = getattr(update, "_tags", [])
        if tags:
            bench = bench.model_copy(update={"tags": tags})
        return bench


async def run_polling(
    *,
    token: str,
    storage: Any,
    runner: Any,
    poll_timeout: int = 25,
    allowed_chat_ids: frozenset[str] | None = None,
) -> None:
    """Entry point called by the CLI command.

    Constructs TelegramBotApi, wraps storage/runner in the connector, and
    blocks on the polling loop.
    """
    api = TelegramBotApi(token)
    connector = _TaggingConnector(
        storage=storage,
        runner=runner,
        telegram=api,
        idempotency=InMemoryTelegramIdempotency(),
        response_client=api,
        response_idempotency=InMemoryTelegramResponseIdempotency(),
    )
    bot = TelegramPollingBot(
        token=token,
        connector=connector,
        api=api,
        poll_timeout=poll_timeout,
        allowed_chat_ids=allowed_chat_ids,
    )
    await bot.run()
