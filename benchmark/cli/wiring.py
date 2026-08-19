"""Component wiring for CLI commands.

Initializes StorageManager, AgentRegistry, BenchmarkRunner, DailyExporter,
ReportGenerator, and optional Telegram/Discord connectors from configuration.
Skips agents with missing API keys and connectors with missing bot tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from benchmark.agents.hermes import HermesAdapter
from benchmark.agents.openai_compatible import OpenAICompatibleAdapter
from benchmark.agents.openclaw import OpenClawAdapter
from benchmark.agents.registry import AgentRegistry
from benchmark.config.settings import Settings
from benchmark.connectors.discord import DiscordAttachmentClient, DiscordConnector
from benchmark.connectors.telegram import TelegramApiClient, TelegramConnector
from benchmark.evaluation.service import EvaluationService
from benchmark.export.daily import DailyExporter
from benchmark.models.domain import DeploymentType
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner, DeploymentResourceConfig
from benchmark.storage.manager import StorageManager

logger = structlog.get_logger(__name__)

# Mapping from settings string values to DeploymentType enum members.
_DEPLOYMENT_TYPE_MAP: dict[str, DeploymentType] = {
    "local_docker": DeploymentType.LOCAL_DOCKER,
    "virtual_machine": DeploymentType.VIRTUAL_MACHINE,
    "vm": DeploymentType.VIRTUAL_MACHINE,
    "managed_container": DeploymentType.MANAGED_CONTAINER,
}


def _resolve_deployment_type(value: str) -> DeploymentType:
    """Resolve a deployment type string to the corresponding enum member.

    Supports both canonical names (local_docker, virtual_machine, managed_container)
    and the short enum values (vm).
    Falls back to LOCAL_DOCKER for unrecognized values with a warning.
    """
    normalized = value.strip().lower()
    deployment = _DEPLOYMENT_TYPE_MAP.get(normalized)
    if deployment is None:
        logger.warning(
            "unknown_deployment_type_defaulting",
            value=value,
            default="local_docker",
        )
        return DeploymentType.LOCAL_DOCKER
    return deployment


class StubTelegramApiClient:
    """Placeholder Telegram API client for wiring.

    Production deployments replace this with a real SDK adapter that
    downloads files and resolves URLs through the Telegram Bot API.
    """

    async def download_file(self, file_id: str) -> bytes | None:
        """Stub: always returns None (URL-only mode)."""
        return None

    async def resolve_file_url(self, file_id: str) -> str | None:
        """Stub: always returns None."""
        return None


class StubDiscordAttachmentClient:
    """Placeholder Discord attachment client for wiring.

    Production deployments replace this with a real SDK adapter that
    downloads attachment bytes or resolves CDN URLs.
    """

    async def download_bytes(self, attachment: object) -> bytes | None:
        """Stub: always returns None (URL-only mode)."""
        return None

    async def resolve_url(self, attachment: object) -> str | None:
        """Stub: always returns None."""
        return None


@dataclass
class AppContext:
    """Holds all wired components needed by CLI commands."""

    storage: StorageManager
    registry: AgentRegistry
    runner: BenchmarkRunner
    exporter: DailyExporter
    report_generator: ReportGenerator
    evaluation_service: EvaluationService
    telegram_connector: TelegramConnector | None = None
    discord_connector: DiscordConnector | None = None


async def create_context(settings: Settings | None = None) -> AppContext:
    """Build and initialize all application components.

    Reads agent endpoints and API keys from settings. Agents whose keys
    are missing are skipped with a warning (Req 11.5).

    Endpoint configuration:
      BENCH_HERMES_ENDPOINT  — URL where Hermes is deployed (VM, ACA, or local Docker)
      BENCH_OPENCLAW_ENDPOINT — URL where OpenClaw is deployed

    Connector configuration:
      BENCH_TELEGRAM_BOT_TOKEN — enables TelegramConnector wiring
      BENCH_DISCORD_BOT_TOKEN  — enables DiscordConnector wiring
    """
    if settings is None:
        settings = Settings()

    # Storage
    storage = StorageManager(db_path=settings.db_path)
    await storage.initialize()

    # Agent registry
    registry = AgentRegistry()
    execution_order: list[tuple[str, DeploymentType]] = []

    # Resolve signing key (shared across all adapters)
    signing_key = settings.signing_key.get_secret_value() or None

    # Register Hermes if API key is available
    hermes_key = settings.hermes_api_key.get_secret_value()
    if hermes_key:
        hermes_deploy = _resolve_deployment_type(settings.hermes_deployment_type)
        adapter = HermesAdapter(
            endpoint=settings.hermes_endpoint,
            api_key=hermes_key,
            signing_key=signing_key,
        )
        registry.register(adapter, hermes_deploy, settings.hermes_endpoint)
        execution_order.append(("hermes", hermes_deploy))
        logger.info(
            "agent_registered",
            agent="hermes",
            endpoint=settings.hermes_endpoint,
            deployment=hermes_deploy.value,
        )
    else:
        logger.warning("agent_skipped_missing_api_key", agent="hermes")

    # Register OpenClaw if API key is available
    openclaw_key = settings.openclaw_api_key.get_secret_value()
    if openclaw_key:
        openclaw_deploy = _resolve_deployment_type(settings.openclaw_deployment_type)
        adapter_oc = OpenClawAdapter(
            endpoint=settings.openclaw_endpoint,
            api_key=openclaw_key,
            signing_key=signing_key,
        )
        registry.register(adapter_oc, openclaw_deploy, settings.openclaw_endpoint)
        execution_order.append(("openclaw", openclaw_deploy))
        logger.info(
            "agent_registered",
            agent="openclaw",
            endpoint=settings.openclaw_endpoint,
            deployment=openclaw_deploy.value,
        )
    else:
        logger.warning("agent_skipped_missing_api_key", agent="openclaw")

    # Register NVIDIA Nemotron agents (direct API, no Docker needed)
    # Requires a separate BENCH_NVIDIA_API_KEY — NOT the Hermes bearer token.
    # Leave unset (or empty) to run only the framework agents (Hermes vs OpenClaw).
    nvidia_api_key = (
        settings.nvidia_api_key.get_secret_value() if hasattr(settings, "nvidia_api_key") else ""
    )
    if nvidia_api_key:
        # Agent 1: Reasoning-focused (verbose system prompt)
        adapter_reasoning = OpenAICompatibleAdapter(
            endpoint="https://integrate.api.nvidia.com/v1",
            model="nvidia/nemotron-3-super-120b-a12b",
            agent_name="nemotron-reasoning",
            agent_version="1.0.0",
            api_key=nvidia_api_key,
            signing_key=signing_key,
        )
        registry.register(
            adapter_reasoning,
            DeploymentType.MANAGED_CONTAINER,
            "https://integrate.api.nvidia.com/v1",
        )
        execution_order.append(("nemotron-reasoning", DeploymentType.MANAGED_CONTAINER))
        logger.info(
            "agent_registered",
            agent="nemotron-reasoning",
            endpoint="https://integrate.api.nvidia.com/v1",
            deployment="managed_container",
        )

        # Agent 2: Concise-focused (brief system prompt)
        adapter_concise = OpenAICompatibleAdapter(
            endpoint="https://integrate.api.nvidia.com/v1",
            model="nvidia/nemotron-3-super-120b-a12b",
            agent_name="nemotron-concise",
            agent_version="1.0.0",
            api_key=nvidia_api_key,
            signing_key=signing_key,
        )
        registry.register(
            adapter_concise, DeploymentType.LOCAL_DOCKER, "https://integrate.api.nvidia.com/v1"
        )
        execution_order.append(("nemotron-concise", DeploymentType.LOCAL_DOCKER))
        logger.info(
            "agent_registered",
            agent="nemotron-concise",
            endpoint="https://integrate.api.nvidia.com/v1",
            deployment="local_docker",
        )
    else:
        logger.warning("nvidia_agents_skipped_missing_api_key")

    # Runner
    runner_config = RunnerConfig(
        execution_order=execution_order,
        delay_between_seconds=settings.delay_seconds,
        timeout_seconds=settings.timeout_seconds,
    )

    # Build deployment resource configs from settings
    deployment_configs: dict[str, DeploymentResourceConfig] = {}
    if settings.hermes_cpu_cores or settings.hermes_memory_mb or settings.hermes_cost_per_hour:
        deployment_configs["hermes"] = DeploymentResourceConfig(
            cpu_cores=settings.hermes_cpu_cores,
            memory_mb=settings.hermes_memory_mb,
            cost_per_hour=settings.hermes_cost_per_hour,
        )
    if (
        settings.openclaw_cpu_cores
        or settings.openclaw_memory_mb
        or settings.openclaw_cost_per_hour
    ):
        deployment_configs["openclaw"] = DeploymentResourceConfig(
            cpu_cores=settings.openclaw_cpu_cores,
            memory_mb=settings.openclaw_memory_mb,
            cost_per_hour=settings.openclaw_cost_per_hour,
        )

    runner = BenchmarkRunner(
        registry=registry,
        storage=storage,
        config=runner_config,
        deployment_configs=deployment_configs if deployment_configs else None,
    )

    # Exporter and report generator
    exporter = DailyExporter(storage=storage, export_dir=Path(settings.export_dir))
    report_generator = ReportGenerator(storage=storage)

    # Evaluation service
    evaluation_service = EvaluationService(storage=storage)

    # Telegram connector (optional)
    telegram_connector: TelegramConnector | None = None
    telegram_token = settings.telegram_bot_token.get_secret_value()
    if telegram_token:
        telegram_client: TelegramApiClient = StubTelegramApiClient()
        telegram_connector = TelegramConnector(
            storage=storage,
            runner=runner,
            telegram=telegram_client,
        )
        logger.info("connector_wired", connector="telegram")
    else:
        logger.info("connector_skipped_missing_token", connector="telegram")

    # Discord connector (optional)
    discord_connector: DiscordConnector | None = None
    discord_token = settings.discord_bot_token.get_secret_value()
    if discord_token:
        discord_client: DiscordAttachmentClient = StubDiscordAttachmentClient()
        discord_connector = DiscordConnector(
            storage=storage,
            runner=runner,
            discord=discord_client,
        )
        logger.info("connector_wired", connector="discord")
    else:
        logger.info("connector_skipped_missing_token", connector="discord")

    return AppContext(
        storage=storage,
        registry=registry,
        runner=runner,
        exporter=exporter,
        report_generator=report_generator,
        evaluation_service=evaluation_service,
        telegram_connector=telegram_connector,
        discord_connector=discord_connector,
    )
