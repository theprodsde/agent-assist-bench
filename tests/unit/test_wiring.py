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


# ---------------------------------------------------------------------------
# BENCH_AGENTS_JSON — generic agent registration
# ---------------------------------------------------------------------------


class TestAgentsJson:
    async def test_single_agent_registered(self, tmp_path):
        agents_json = (
            '[{"name":"librechat","endpoint":"http://localhost:9000/v1","model":"gpt-4o",'
            '"api_key":"sk-test","deployment_type":"local_docker"}]'
        )
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": agents_json}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            names = [name for name, _ in ctx.registry.list_available()]
            assert "librechat" in names
        finally:
            await ctx.storage.close()

    async def test_multiple_agents_registered(self, tmp_path):
        agents_json = (
            '[{"name":"agent-a","endpoint":"http://localhost:9001/v1","model":"llama3","api_key":"k1"},'
            '{"name":"agent-b","endpoint":"http://localhost:9002/v1","model":"mistral","api_key":"k2"}]'
        )
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": agents_json}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            names = [name for name, _ in ctx.registry.list_available()]
            assert "agent-a" in names
            assert "agent-b" in names
        finally:
            await ctx.storage.close()

    async def test_json_agents_added_alongside_hermes(self, tmp_path):
        agents_json = '[{"name":"extra","endpoint":"http://localhost:9003/v1","model":"phi3"}]'
        env = {
            **_base_env(tmp_path),
            "BENCH_HERMES_API_KEY": "hermes-key",
            "BENCH_AGENTS_JSON": agents_json,
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            names = [name for name, _ in ctx.registry.list_available()]
            assert "hermes" in names
            assert "extra" in names
        finally:
            await ctx.storage.close()

    async def test_invalid_json_skips_gracefully(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": "not-json"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.registry.list_available() == []
        finally:
            await ctx.storage.close()

    async def test_item_missing_required_fields_skipped(self, tmp_path):
        agents_json = '[{"name":"incomplete"}]'
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": agents_json}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.registry.list_available() == []
        finally:
            await ctx.storage.close()

    async def test_empty_agents_json_skipped(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": ""}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.registry.list_available() == []
        finally:
            await ctx.storage.close()

    async def test_non_list_json_skipped(self, tmp_path):
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": '{"name":"oops","endpoint":"x","model":"y"}'}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.registry.list_available() == []
        finally:
            await ctx.storage.close()

    async def test_resource_config_from_json(self, tmp_path):
        agents_json = (
            '[{"name":"heavy","endpoint":"http://localhost:9004/v1","model":"llama3",'
            '"cpu_cores":8,"memory_mb":16384,"cost_per_hour":1.2}]'
        )
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": agents_json}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            assert ctx.runner._deployment_configs is not None
            rc = ctx.runner._deployment_configs["heavy"]
            assert rc.cpu_cores == 8.0
            assert rc.memory_mb == 16384.0
            assert rc.cost_per_hour == 1.2
        finally:
            await ctx.storage.close()

    async def test_managed_container_deployment_type_in_json(self, tmp_path):
        agents_json = (
            '[{"name":"cloud-agent","endpoint":"https://api.example.com/v1","model":"gpt-4o",'
            '"api_key":"k","deployment_type":"managed_container"}]'
        )
        env = {**_base_env(tmp_path), "BENCH_AGENTS_JSON": agents_json}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        try:
            order = ctx.runner._config.execution_order
            assert ("cloud-agent", DeploymentType.MANAGED_CONTAINER) in order
        finally:
            await ctx.storage.close()
