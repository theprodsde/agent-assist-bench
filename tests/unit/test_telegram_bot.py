"""Unit tests for benchmark/bots/telegram.py.

Covers TelegramBotApi (HTTP layer), TelegramPollingBot (dispatch loop),
_TaggingConnector (tag injection), and run_polling (entry point).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from benchmark.bots.telegram import (
    TelegramBotApi,
    TelegramPollingBot,
    _extract_tags_and_prompt,
    _TaggingConnector,
    run_polling,
)
from benchmark.connectors.telegram import (
    TelegramChat,
    TelegramDispatchResult,
    TelegramMessage,
    TelegramUpdate,
)

# ---------------------------------------------------------------------------
# _extract_tags_and_prompt
# ---------------------------------------------------------------------------


class TestExtractTagsAndPrompt:
    def test_no_tags(self):
        tags, prompt = _extract_tags_and_prompt("Write a binary search in Python")
        assert tags == []
        assert prompt == "Write a binary search in Python"

    def test_single_tag_prefix(self):
        tags, prompt = _extract_tags_and_prompt("#coding Write a binary search")
        assert tags == ["coding"]
        assert prompt == "Write a binary search"

    def test_multiple_tags(self):
        tags, prompt = _extract_tags_and_prompt("#research #devops Explain Kubernetes")
        assert set(tags) == {"research", "devops"}
        assert prompt == "Explain Kubernetes"

    def test_tag_in_middle(self):
        tags, prompt = _extract_tags_and_prompt("Hello #research world")
        assert tags == ["research"]
        assert prompt == "Hello  world".strip()

    def test_tag_at_end(self):
        tags, prompt = _extract_tags_and_prompt("Explain Docker #devops")
        assert tags == ["devops"]
        assert "Explain Docker" in prompt

    def test_tags_are_lowercased(self):
        tags, _ = _extract_tags_and_prompt("#CODING #DevOps question")
        assert tags == ["coding", "devops"]

    def test_empty_string(self):
        tags, prompt = _extract_tags_and_prompt("")
        assert tags == []
        assert prompt == ""

    def test_only_tags(self):
        tags, prompt = _extract_tags_and_prompt("#coding #research")
        assert set(tags) == {"coding", "research"}
        assert prompt == ""


# ---------------------------------------------------------------------------
# TelegramBotApi — HTTP layer via MockTransport
# ---------------------------------------------------------------------------


def _make_api(handler: Any) -> TelegramBotApi:
    api = TelegramBotApi.__new__(TelegramBotApi)
    api._base = "https://api.telegram.org/botTOKEN"
    api._file_base = "https://api.telegram.org/file/botTOKEN"
    api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return api


class TestTelegramBotApi:
    def test_init_sets_base_urls(self):
        api = TelegramBotApi(token="123:ABC")
        assert "123:ABC" in api._base
        assert "123:ABC" in api._file_base

    async def test_get_updates_returns_results(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"ok": True, "result": [{"update_id": 1, "message": {"text": "hi"}}]},
            )

        api = _make_api(handler)
        updates = await api.get_updates(offset=0)
        assert len(updates) == 1
        assert updates[0]["update_id"] == 1
        await api.close()

    async def test_get_updates_empty_when_ok_false(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": False})

        api = _make_api(handler)
        updates = await api.get_updates()
        assert updates == []
        await api.close()

    async def test_get_updates_empty_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "result": []})

        api = _make_api(handler)
        updates = await api.get_updates(offset=5)
        assert updates == []
        await api.close()

    async def test_send_message_plain(self):
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            sent.append(_json.loads(request.content))
            return httpx.Response(200, json={"ok": True})

        api = _make_api(handler)
        await api.send_message("123456", "Hello")
        assert sent[0]["chat_id"] == "123456"
        assert sent[0]["text"] == "Hello"
        await api.close()

    async def test_send_message_truncates_at_4096(self):
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            sent.append(_json.loads(request.content))
            return httpx.Response(200, json={"ok": True})

        api = _make_api(handler)
        long_text = "x" * 5000
        await api.send_message("123", long_text)
        assert len(sent[0]["text"]) <= 4096
        assert sent[0]["text"].endswith("…")
        await api.close()

    async def test_send_message_with_thread_id(self):
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            sent.append(_json.loads(request.content))
            return httpx.Response(200, json={"ok": True})

        api = _make_api(handler)
        await api.send_message("123:42", "Hello thread")
        assert sent[0]["chat_id"] == "123"
        assert sent[0]["message_thread_id"] == 42
        await api.close()

    async def test_download_file_always_none(self):
        api = TelegramBotApi.__new__(TelegramBotApi)
        result = await api.download_file("file-123")
        assert result is None

    async def test_resolve_file_url_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "photos/file.jpg"}}
            )

        api = _make_api(handler)
        url = await api.resolve_file_url("file-abc")
        assert url is not None
        assert "photos/file.jpg" in url
        await api.close()

    async def test_resolve_file_url_missing_path(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True, "result": {}})

        api = _make_api(handler)
        url = await api.resolve_file_url("file-abc")
        assert url is None
        await api.close()

    async def test_resolve_file_url_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        api = _make_api(handler)
        url = await api.resolve_file_url("file-abc")
        assert url is None
        await api.close()

    async def test_resolve_file_url_network_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        api = _make_api(handler)
        url = await api.resolve_file_url("file-abc")
        assert url is None
        await api.close()

    async def test_close(self):
        api = TelegramBotApi(token="123:ABC")
        await api.close()  # should not raise


# ---------------------------------------------------------------------------
# TelegramPollingBot — dispatch loop
# ---------------------------------------------------------------------------


def _make_raw_update(update_id: int = 1, chat_id: int = 999, text: str = "hello") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id},
            "text": text,
        },
    }


class TestTelegramPollingBot:
    def _make_bot(
        self,
        *,
        allowed_chat_ids: frozenset[str] | None = None,
    ) -> tuple[TelegramPollingBot, MagicMock]:
        connector = MagicMock()
        connector.handle_update = AsyncMock(
            return_value=TelegramDispatchResult(accepted=True, delivered=True)
        )
        api = MagicMock(spec=TelegramBotApi)
        api.get_updates = AsyncMock(return_value=[])
        api.close = AsyncMock()
        bot = TelegramPollingBot(
            token="TOKEN",
            connector=connector,
            api=api,
            allowed_chat_ids=allowed_chat_ids,
        )
        return bot, connector

    def test_init_defaults(self):
        bot, _ = self._make_bot()
        assert bot._running is False
        assert bot._offset is None
        assert bot._allowed_chat_ids == frozenset()

    def test_init_with_allowed_chat_ids(self):
        bot, _ = self._make_bot(allowed_chat_ids=frozenset({"123", "456"}))
        assert "123" in bot._allowed_chat_ids

    def test_stop_sets_running_false(self):
        bot, _ = self._make_bot()
        bot._running = True
        bot._stop()
        assert bot._running is False

    async def test_handle_invalid_update_is_skipped(self):
        bot, connector = self._make_bot()
        await bot._handle({"update_id": "not-an-int"})
        connector.handle_update.assert_not_called()

    async def test_handle_update_no_message_is_skipped(self):
        bot, connector = self._make_bot()
        await bot._handle({"update_id": 1})
        connector.handle_update.assert_not_called()

    async def test_handle_authorized_chat_dispatches(self):
        bot, connector = self._make_bot(allowed_chat_ids=frozenset({"999"}))
        await bot._handle(_make_raw_update(chat_id=999))
        connector.handle_update.assert_called_once()

    async def test_handle_unauthorized_chat_is_dropped(self):
        bot, connector = self._make_bot(allowed_chat_ids=frozenset({"111"}))
        await bot._handle(_make_raw_update(chat_id=999))
        connector.handle_update.assert_not_called()

    async def test_handle_no_allowlist_accepts_all(self):
        bot, connector = self._make_bot(allowed_chat_ids=None)
        await bot._handle(_make_raw_update(chat_id=999))
        connector.handle_update.assert_called_once()

    async def test_handle_strips_tags_from_text(self):
        bot, connector = self._make_bot()
        await bot._handle(_make_raw_update(text="#coding Write a sort"))
        connector.handle_update.assert_called_once()
        update_passed = connector.handle_update.call_args[0][0]
        assert update_passed.message is not None
        assert "#coding" not in (update_passed.message.text or "")
        assert "Write a sort" in (update_passed.message.text or "")

    async def test_handle_connector_error_logs_warning(self):
        bot, connector = self._make_bot()
        from benchmark.connectors.telegram import TelegramConnectorError

        connector.handle_update = AsyncMock(
            return_value=TelegramDispatchResult(
                accepted=False,
                error=TelegramConnectorError(code="storage_failure", message="db error"),
            )
        )
        await bot._handle(_make_raw_update())
        connector.handle_update.assert_called_once()

    async def test_run_processes_one_update_then_stops(self):
        bot, connector = self._make_bot()
        bot._api.get_updates = AsyncMock(
            side_effect=[
                [_make_raw_update(update_id=5)],
                asyncio.CancelledError(),
            ]
        )

        async def _run_briefly() -> None:
            with contextlib.suppress(asyncio.CancelledError):
                await bot.run()

        await _run_briefly()
        connector.handle_update.assert_called_once()
        assert bot._offset == 6

    async def test_run_retries_on_timeout(self):
        bot, connector = self._make_bot()
        call_count = 0

        async def _noop_sleep(*args: Any, **kwargs: Any) -> None:
            pass

        async def side_effect(*args: Any, **kwargs: Any) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timeout")
            raise asyncio.CancelledError()

        bot._api.get_updates = AsyncMock(side_effect=side_effect)

        async def _run_briefly() -> None:
            with contextlib.suppress(asyncio.CancelledError):
                await bot.run()

        with patch("asyncio.sleep", side_effect=_noop_sleep):
            await _run_briefly()

        assert call_count >= 1

    async def test_run_retries_on_http_status_error(self):
        bot, _ = self._make_bot()
        call_count = 0

        async def _noop_sleep(*args: Any, **kwargs: Any) -> None:
            pass

        async def side_effect(*args: Any, **kwargs: Any) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "error",
                    request=MagicMock(),
                    response=MagicMock(status_code=429),
                )
            raise asyncio.CancelledError()

        bot._api.get_updates = AsyncMock(side_effect=side_effect)

        async def _run_briefly() -> None:
            with contextlib.suppress(asyncio.CancelledError):
                await bot.run()

        with patch("asyncio.sleep", side_effect=_noop_sleep):
            await _run_briefly()

        assert call_count >= 1


# ---------------------------------------------------------------------------
# _TaggingConnector — tag propagation
# ---------------------------------------------------------------------------


class TestTaggingConnector:
    async def test_tags_injected_into_benchmark(self, tmp_path):
        from benchmark.agents.registry import AgentRegistry
        from benchmark.runner.config import RunnerConfig
        from benchmark.runner.engine import BenchmarkRunner
        from benchmark.storage.manager import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path=str(db_path))
        await storage.initialize()

        registry = AgentRegistry()
        config = RunnerConfig(execution_order=[], delay_between_seconds=0.0, timeout_seconds=5.0)
        runner = BenchmarkRunner(registry=registry, storage=storage, config=config)

        api = MagicMock(spec=TelegramBotApi)
        connector = _TaggingConnector(storage=storage, runner=runner, telegram=api)

        update = TelegramUpdate(
            update_id=1,
            message=TelegramMessage(
                message_id=1,
                chat=TelegramChat(id=12345),
                text="Write a sort",
            ),
        )
        update._tags = ["coding", "research"]  # type: ignore[attr-defined]

        benchmark = await connector._to_benchmark(update)
        assert set(benchmark.tags) == {"coding", "research"}

        await storage.close()


# ---------------------------------------------------------------------------
# run_polling — entry point wiring
# ---------------------------------------------------------------------------


class TestRunPolling:
    async def test_run_polling_builds_bot_and_runs(self, tmp_path):
        from unittest.mock import patch as _patch

        from benchmark.agents.registry import AgentRegistry
        from benchmark.runner.config import RunnerConfig
        from benchmark.runner.engine import BenchmarkRunner
        from benchmark.storage.manager import StorageManager

        db_path = tmp_path / "test.db"
        storage = StorageManager(db_path=str(db_path))
        await storage.initialize()

        registry = AgentRegistry()
        config = RunnerConfig(execution_order=[], delay_between_seconds=0.0, timeout_seconds=5.0)
        runner = BenchmarkRunner(registry=registry, storage=storage, config=config)

        async def _noop_run(self) -> None:  # noqa: ANN001
            pass

        with _patch("benchmark.bots.telegram.TelegramPollingBot.run", new=_noop_run):
            await run_polling(
                token="TOKEN",
                storage=storage,
                runner=runner,
                allowed_chat_ids=frozenset({"123"}),
            )

        await storage.close()
