"""Unit tests for VM deployment wiring.

Verifies that the wiring correctly uses the configured deployment type
when registering agents, supporting all DeploymentType values.

Requirements: 3.3, 3.4, 11.4; ADR-0006, ADR-0008
"""

import os
from unittest.mock import patch

import pytest

from benchmark.cli.wiring import _resolve_deployment_type, create_context
from benchmark.config.settings import Settings
from benchmark.models.domain import DeploymentType


class TestResolveDeploymentType:
    """Test the _resolve_deployment_type helper function."""

    def test_local_docker(self) -> None:
        assert _resolve_deployment_type("local_docker") == DeploymentType.LOCAL_DOCKER

    def test_virtual_machine(self) -> None:
        assert _resolve_deployment_type("virtual_machine") == DeploymentType.VIRTUAL_MACHINE

    def test_vm_shorthand(self) -> None:
        assert _resolve_deployment_type("vm") == DeploymentType.VIRTUAL_MACHINE

    def test_managed_container(self) -> None:
        assert _resolve_deployment_type("managed_container") == DeploymentType.MANAGED_CONTAINER

    def test_case_insensitive(self) -> None:
        assert _resolve_deployment_type("Virtual_Machine") == DeploymentType.VIRTUAL_MACHINE
        assert _resolve_deployment_type("LOCAL_DOCKER") == DeploymentType.LOCAL_DOCKER
        assert _resolve_deployment_type("MANAGED_CONTAINER") == DeploymentType.MANAGED_CONTAINER

    def test_whitespace_stripped(self) -> None:
        assert _resolve_deployment_type("  virtual_machine  ") == DeploymentType.VIRTUAL_MACHINE

    def test_unknown_value_defaults_to_local_docker(self) -> None:
        assert _resolve_deployment_type("unknown") == DeploymentType.LOCAL_DOCKER


class TestDeploymentTypeSettings:
    """Test that deployment type settings default correctly."""

    def test_default_hermes_deployment_type(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.hermes_deployment_type == "local_docker"

    def test_default_openclaw_deployment_type(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.openclaw_deployment_type == "local_docker"

    def test_hermes_deployment_type_from_env(self) -> None:
        with patch.dict(
            os.environ, {"BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine"}, clear=True
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.hermes_deployment_type == "virtual_machine"

    def test_openclaw_deployment_type_from_env(self) -> None:
        with patch.dict(
            os.environ, {"BENCH_OPENCLAW_DEPLOYMENT_TYPE": "managed_container"}, clear=True
        ):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.openclaw_deployment_type == "managed_container"


class TestWiringWithVMDeployment:
    """Test that create_context registers agents with the correct deployment type."""

    @pytest.mark.asyncio
    async def test_hermes_registered_as_vm(self, tmp_path: str) -> None:
        env = {
            "BENCH_HERMES_API_KEY": "test-key",
            "BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine",
            "BENCH_HERMES_ENDPOINT": "http://10.0.1.4:8001",
            "BENCH_DB_PATH": str(tmp_path) + "/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        # Verify hermes is registered with VIRTUAL_MACHINE deployment type
        agent = ctx.registry.get("hermes", DeploymentType.VIRTUAL_MACHINE)
        assert agent is not None
        assert agent.name == "hermes"

        # Verify it's NOT registered under LOCAL_DOCKER
        assert ctx.registry.get("hermes", DeploymentType.LOCAL_DOCKER) is None

        # Verify endpoint is correctly recorded
        endpoint = ctx.registry.get_endpoint("hermes", DeploymentType.VIRTUAL_MACHINE)
        assert endpoint == "http://10.0.1.4:8001"

    @pytest.mark.asyncio
    async def test_openclaw_registered_as_vm(self, tmp_path: str) -> None:
        env = {
            "BENCH_OPENCLAW_API_KEY": "test-key",
            "BENCH_OPENCLAW_DEPLOYMENT_TYPE": "virtual_machine",
            "BENCH_OPENCLAW_ENDPOINT": "http://10.0.1.5:8002",
            "BENCH_DB_PATH": str(tmp_path) + "/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        agent = ctx.registry.get("openclaw", DeploymentType.VIRTUAL_MACHINE)
        assert agent is not None
        assert agent.name == "openclaw"
        assert ctx.registry.get("openclaw", DeploymentType.LOCAL_DOCKER) is None

    @pytest.mark.asyncio
    async def test_default_deployment_is_local_docker(self, tmp_path: str) -> None:
        env = {
            "BENCH_HERMES_API_KEY": "test-key",
            "BENCH_DB_PATH": str(tmp_path) + "/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        # Default deployment type is local_docker
        agent = ctx.registry.get("hermes", DeploymentType.LOCAL_DOCKER)
        assert agent is not None
        assert agent.name == "hermes"

    @pytest.mark.asyncio
    async def test_managed_container_deployment(self, tmp_path: str) -> None:
        env = {
            "BENCH_HERMES_API_KEY": "test-key",
            "BENCH_HERMES_DEPLOYMENT_TYPE": "managed_container",
            "BENCH_DB_PATH": str(tmp_path) + "/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        agent = ctx.registry.get("hermes", DeploymentType.MANAGED_CONTAINER)
        assert agent is not None
        assert agent.name == "hermes"

    @pytest.mark.asyncio
    async def test_mixed_deployment_types(self, tmp_path: str) -> None:
        env = {
            "BENCH_HERMES_API_KEY": "hermes-key",
            "BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine",
            "BENCH_OPENCLAW_API_KEY": "openclaw-key",
            "BENCH_OPENCLAW_DEPLOYMENT_TYPE": "managed_container",
            "BENCH_DB_PATH": str(tmp_path) + "/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        # Hermes is VM
        hermes = ctx.registry.get("hermes", DeploymentType.VIRTUAL_MACHINE)
        assert hermes is not None
        assert hermes.name == "hermes"

        # OpenClaw is managed container
        openclaw = ctx.registry.get("openclaw", DeploymentType.MANAGED_CONTAINER)
        assert openclaw is not None
        assert openclaw.name == "openclaw"

    @pytest.mark.asyncio
    async def test_execution_order_uses_configured_deployment(self, tmp_path: str) -> None:
        env = {
            "BENCH_HERMES_API_KEY": "hermes-key",
            "BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine",
            "BENCH_OPENCLAW_API_KEY": "openclaw-key",
            "BENCH_OPENCLAW_DEPLOYMENT_TYPE": "vm",
            "BENCH_DB_PATH": str(tmp_path) + "/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            ctx = await create_context(settings)

        # Runner config execution order should reference VM deployment
        execution_order = ctx.runner._config.execution_order
        assert ("hermes", DeploymentType.VIRTUAL_MACHINE) in execution_order
        assert ("openclaw", DeploymentType.VIRTUAL_MACHINE) in execution_order
