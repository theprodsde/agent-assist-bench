"""Unit tests for benchmark/cli/wiring.py — create_context and stubs."""

from __future__ import annotations

import os
from unittest.mock import patch

from benchmark.cli.wiring import (
    AppContext,
    StubDiscordAttachmentClient,
    StubTelegramApiClient,
    create_context,
)
from benchmark.config.settings import Settings
from benchmark.models.domain import DeploymentType

# ---------------------------------------------------------------------------
# Stub clients
# ---------------------------------------------------------------------------


class TestStubTelegramApiClient:
    async def test_download_file_returns_none(self):
        client = StubTelegramApiClient()
        result = await client.download_file("file-123")
        assert result is None

    async def test_resolve_file_url_returns_none(self):
        client = StubTelegramApiClient()
        result = await client.resolve_file_url("file-123")
        assert result is None


class TestStubDiscordAttachmentClient:
    async def test_download_bytes_returns_none(self):
        client = StubDiscordAttachmentClient()
        result = await client.download_bytes(object())
        assert result is None

    async def test_resolve_url_returns_none(self):
        client = StubDiscordAttachmentClient()
        result = await client.resolve_url(object())
        assert result is None


# ---------------------------------------------------------------------------
# create_context — agent registration paths
# ---------------------------------------------------------------------------


def _base_env(tmp_path) -> dict:
    return {
        "BENCH_DB_PATH": str(tmp_path / "test.db"),
        "BENCH_DELAY_SECONDS": "0",
        "BENCH_TIMEOUT_SECONDS": "5",
        "BENCH_HERMES_API_KEY": "",
        "BENCH_OPENCLAW_API_KEY": "",
        "BENCH_TELEGRAM_BOT_TOKEN": "",
        "BENCH_DISCORD_BOT_TOKEN": "",
        "BENCH_NVIDIA_API_KEY": "",
        "BENCH_SIGNING_KEY": "",
    }


class TestCreateContext:
    async def test_no_api_keys_skips_all_agents(self, tmp_path):
        env = _base_env(tmp_path)
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.registry.list_available() == []
            assert ctx.telegram_connector is None
            assert ctx.discord_connector is None
        finally:
            await ctx.storage.close()

    async def test_hermes_key_registers_hermes(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_HERMES_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            available = ctx.registry.list_available()
            names = [name for name, _ in available]
            assert "hermes" in names
            assert "openclaw" not in names
        finally:
            await ctx.storage.close()

    async def test_both_keys_register_both_agents(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_HERMES_API_KEY": "key-h",
            "BENCH_OPENCLAW_API_KEY": "key-o",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            available = ctx.registry.list_available()
            names = [name for name, _ in available]
            assert "hermes" in names
            assert "openclaw" in names
        finally:
            await ctx.storage.close()

    async def test_execution_order_matches_registered_agents(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_HERMES_API_KEY": "key-h",
            "BENCH_OPENCLAW_API_KEY": "key-o",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            order = ctx.runner._config.execution_order
            assert ("hermes", DeploymentType.LOCAL_DOCKER) in order
            assert ("openclaw", DeploymentType.LOCAL_DOCKER) in order
            assert order.index(("hermes", DeploymentType.LOCAL_DOCKER)) < order.index(
                ("openclaw", DeploymentType.LOCAL_DOCKER)
            )
        finally:
            await ctx.storage.close()

    async def test_telegram_token_wires_connector(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_TELEGRAM_BOT_TOKEN": "123:TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.telegram_connector is not None
            assert ctx.discord_connector is None
        finally:
            await ctx.storage.close()

    async def test_discord_token_wires_connector(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_DISCORD_BOT_TOKEN": "discord-token"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.discord_connector is not None
            assert ctx.telegram_connector is None
        finally:
            await ctx.storage.close()

    async def test_both_connectors_wired_together(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_TELEGRAM_BOT_TOKEN": "tg-token",
            "BENCH_DISCORD_BOT_TOKEN": "dc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.telegram_connector is not None
            assert ctx.discord_connector is not None
        finally:
            await ctx.storage.close()

    async def test_nvidia_key_registers_nemotron_agents(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_NVIDIA_API_KEY": "nvapi-key"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            available = ctx.registry.list_available()
            names = [name for name, _ in available]
            assert "nemotron-reasoning" in names
            assert "nemotron-concise" in names
        finally:
            await ctx.storage.close()

    async def test_virtual_machine_deployment_type(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_HERMES_API_KEY": "key-h",
            "BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            order = ctx.runner._config.execution_order
            assert ("hermes", DeploymentType.VIRTUAL_MACHINE) in order
        finally:
            await ctx.storage.close()

    async def test_managed_container_deployment_type(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_OPENCLAW_API_KEY": "key-o",
            "BENCH_OPENCLAW_DEPLOYMENT_TYPE": "managed_container",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            order = ctx.runner._config.execution_order
            assert ("openclaw", DeploymentType.MANAGED_CONTAINER) in order
        finally:
            await ctx.storage.close()

    async def test_deployment_resource_configs_wired(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_HERMES_API_KEY": "key-h",
            "BENCH_HERMES_CPU_CORES": "8",
            "BENCH_HERMES_MEMORY_MB": "16384",
            "BENCH_HERMES_COST_PER_HOUR": "1.5",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.runner._deployment_configs is not None
            hermes_rc = ctx.runner._deployment_configs["hermes"]
            assert hermes_rc.cpu_cores == 8.0
            assert hermes_rc.memory_mb == 16384.0
            assert hermes_rc.cost_per_hour == 1.5
        finally:
            await ctx.storage.close()

    async def test_signing_key_propagated(self, tmp_path):
        env = {
            **_base_env(tmp_path),
            "BENCH_HERMES_API_KEY": "key-h",
            "BENCH_SIGNING_KEY": "my-signing-key",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            hermes_agent = ctx.registry.get("hermes", DeploymentType.LOCAL_DOCKER)
            assert hermes_agent is not None
            # HermesAdapter delegates to _inner (OpenAICompatibleAdapter)
            assert hermes_agent._inner._signing_key == "my-signing-key"
        finally:
            await ctx.storage.close()

    async def test_context_has_all_components(self, tmp_path):
        env = _base_env(tmp_path)
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.storage is not None
            assert ctx.registry is not None
            assert ctx.runner is not None
            assert ctx.exporter is not None
            assert ctx.report_generator is not None
            assert ctx.evaluation_service is not None
        finally:
            await ctx.storage.close()

    async def test_none_settings_loads_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BENCH_DB_PATH", str(tmp_path / "default.db"))
        monkeypatch.setenv("BENCH_HERMES_API_KEY", "")
        monkeypatch.setenv("BENCH_OPENCLAW_API_KEY", "")
        monkeypatch.setenv("BENCH_TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setenv("BENCH_DISCORD_BOT_TOKEN", "")
        ctx = await create_context(None)
        try:
            assert isinstance(ctx, AppContext)
        finally:
            await ctx.storage.close()
