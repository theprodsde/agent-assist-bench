"""Component wiring for CLI commands.

Initializes StorageManager, AgentRegistry, BenchmarkRunner, DailyExporter,
ReportGenerator, and optional Telegram/Discord connectors from configuration.
Skips agents with missing API keys and connectors with missing bot tokens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Callable

    from benchmark.agents.base import AgentAdapter

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


@dataclass
class _AgentWireSpec:
    """Config-driven spec for a single agent to be wired into the registry."""

    name: str
    endpoint: str
    deployment_type: DeploymentType
    factory: Callable[[], AgentAdapter]
    cpu_cores: float | None = None
    memory_mb: float | None = None
    cost_per_hour: float | None = None


def _build_agent_specs(settings: Settings, signing_key: str | None) -> list[_AgentWireSpec]:
    """Build agent wire specs from settings. Agents with empty API keys are skipped."""
    specs: list[_AgentWireSpec] = []

    if hermes_key := settings.hermes_api_key.get_secret_value():
        specs.append(
            _AgentWireSpec(
                name="hermes",
                endpoint=settings.hermes_endpoint,
                deployment_type=_resolve_deployment_type(settings.hermes_deployment_type),
                factory=lambda: HermesAdapter(
                    endpoint=settings.hermes_endpoint,
                    api_key=hermes_key,
                    signing_key=signing_key,
                    input_price_per_mtok=settings.hermes_input_price_per_mtok,
                    output_price_per_mtok=settings.hermes_output_price_per_mtok,
                ),
                cpu_cores=settings.hermes_cpu_cores,
                memory_mb=settings.hermes_memory_mb,
                cost_per_hour=settings.hermes_cost_per_hour,
            )
        )
    else:
        logger.warning("agent_skipped_missing_api_key", agent="hermes")

    if openclaw_key := settings.openclaw_api_key.get_secret_value():
        specs.append(
            _AgentWireSpec(
                name="openclaw",
                endpoint=settings.openclaw_endpoint,
                deployment_type=_resolve_deployment_type(settings.openclaw_deployment_type),
                factory=lambda: OpenClawAdapter(
                    endpoint=settings.openclaw_endpoint,
                    api_key=openclaw_key,
                    signing_key=signing_key,
                    input_price_per_mtok=settings.openclaw_input_price_per_mtok,
                    output_price_per_mtok=settings.openclaw_output_price_per_mtok,
                ),
                cpu_cores=settings.openclaw_cpu_cores,
                memory_mb=settings.openclaw_memory_mb,
                cost_per_hour=settings.openclaw_cost_per_hour,
            )
        )
    else:
        logger.warning("agent_skipped_missing_api_key", agent="openclaw")

    if nvidia_key := settings.nvidia_api_key.get_secret_value():
        _nvidia_endpoint = "https://integrate.api.nvidia.com/v1"
        _nvidia_model = "nvidia/nemotron-3-super-120b-a12b"
        specs.append(
            _AgentWireSpec(
                name="nemotron-reasoning",
                endpoint=_nvidia_endpoint,
                deployment_type=DeploymentType.MANAGED_CONTAINER,
                factory=lambda: OpenAICompatibleAdapter(
                    endpoint=_nvidia_endpoint,
                    model=_nvidia_model,
                    agent_name="nemotron-reasoning",
                    agent_version="1.0.0",
                    api_key=nvidia_key,
                    signing_key=signing_key,
                    input_price_per_mtok=settings.nvidia_input_price_per_mtok,
                    output_price_per_mtok=settings.nvidia_output_price_per_mtok,
                ),
            )
        )
        specs.append(
            _AgentWireSpec(
                name="nemotron-concise",
                endpoint=_nvidia_endpoint,
                deployment_type=DeploymentType.LOCAL_DOCKER,
                factory=lambda: OpenAICompatibleAdapter(
                    endpoint=_nvidia_endpoint,
                    model=_nvidia_model,
                    agent_name="nemotron-concise",
                    agent_version="1.0.0",
                    api_key=nvidia_key,
                    signing_key=signing_key,
                    input_price_per_mtok=settings.nvidia_input_price_per_mtok,
                    output_price_per_mtok=settings.nvidia_output_price_per_mtok,
                ),
            )
        )
    else:
        logger.warning("nvidia_agents_skipped_missing_api_key")

    specs.extend(_build_json_agent_specs(settings, signing_key))
    return specs


def _build_json_agent_specs(settings: Settings, signing_key: str | None) -> list[_AgentWireSpec]:
    """Parse BENCH_AGENTS_JSON and build wire specs for each entry.

    Each JSON item must have: name (str), endpoint (str), model (str).
    Optional: api_key (str), deployment_type (str), cpu_cores (float),
    memory_mb (float), cost_per_hour (float), input_price_per_mtok (float),
    output_price_per_mtok (float).

    Entries with a duplicate name+deployment_type pair override earlier ones
    (same as AgentRegistry.register semantics).
    """
    raw = settings.agents_json.strip()
    if not raw:
        return []

    try:
        items: list[Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("agents_json_parse_error", error=str(exc))
        return []

    if not isinstance(items, list):
        logger.error("agents_json_must_be_list")
        return []

    specs: list[_AgentWireSpec] = []
    for item in items:
        if not isinstance(item, dict):
            logger.warning("agents_json_item_skipped_not_dict", item=item)
            continue
        name = item.get("name", "").strip()
        endpoint = item.get("endpoint", "").strip()
        model = item.get("model", "").strip()
        if not name or not endpoint or not model:
            logger.warning(
                "agents_json_item_skipped_missing_fields",
                name=name,
                endpoint=endpoint,
                model=model,
            )
            continue
        api_key: str | None = item.get("api_key") or None
        deployment_type = _resolve_deployment_type(item.get("deployment_type", "local_docker"))

        input_price: float | None = item.get("input_price_per_mtok")
        output_price: float | None = item.get("output_price_per_mtok")

        def _make_factory(
            n: str,
            e: str,
            m: str,
            k: str | None,
            sk: str | None,
            in_price: float | None,
            out_price: float | None,
        ) -> Callable[[], AgentAdapter]:
            def _factory() -> AgentAdapter:
                return OpenAICompatibleAdapter(
                    endpoint=e,
                    model=m,
                    agent_name=n,
                    agent_version="1.0.0",
                    api_key=k,
                    signing_key=sk,
                    input_price_per_mtok=in_price,
                    output_price_per_mtok=out_price,
                )

            return _factory

        specs.append(
            _AgentWireSpec(
                name=name,
                endpoint=endpoint,
                deployment_type=deployment_type,
                factory=_make_factory(
                    name, endpoint, model, api_key, signing_key, input_price, output_price
                ),
                cpu_cores=item.get("cpu_cores"),
                memory_mb=item.get("memory_mb"),
                cost_per_hour=item.get("cost_per_hour"),
            )
        )
        logger.debug("agents_json_item_loaded", name=name, endpoint=endpoint)

    return specs


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


def _assemble_context(settings: Settings, storage: StorageManager) -> AppContext:
    """Wire all components into an AppContext given an initialised StorageManager.

    This is a pure synchronous function so that coverage can trace every branch
    regardless of the Python / coverage version. create_context() calls this
    after the single async step (await storage.initialize()).
    """
    signing_key = settings.signing_key.get_secret_value() or None

    registry = AgentRegistry()
    execution_order: list[tuple[str, DeploymentType]] = []
    deployment_configs: dict[str, DeploymentResourceConfig] = {}

    for spec in _build_agent_specs(settings, signing_key):
        adapter = spec.factory()
        registry.register(adapter, spec.deployment_type, spec.endpoint)
        execution_order.append((spec.name, spec.deployment_type))
        if spec.cpu_cores or spec.memory_mb or spec.cost_per_hour:
            deployment_configs[spec.name] = DeploymentResourceConfig(
                cpu_cores=spec.cpu_cores,
                memory_mb=spec.memory_mb,
                cost_per_hour=spec.cost_per_hour,
            )
        logger.info(
            "agent_registered",
            agent=spec.name,
            endpoint=spec.endpoint,
            deployment=spec.deployment_type.value,
        )

    runner_config = RunnerConfig(
        execution_order=execution_order,
        delay_between_seconds=settings.delay_seconds,
        timeout_seconds=settings.timeout_seconds,
    )
    runner = BenchmarkRunner(
        registry=registry,
        storage=storage,
        config=runner_config,
        deployment_configs=deployment_configs if deployment_configs else None,
    )

    exporter = DailyExporter(storage=storage, export_dir=Path(settings.export_dir))
    report_generator = ReportGenerator(storage=storage)
    evaluation_service = EvaluationService(storage=storage)

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

    storage = StorageManager(db_path=settings.db_path)
    await storage.initialize()

    return _assemble_context(settings, storage)
