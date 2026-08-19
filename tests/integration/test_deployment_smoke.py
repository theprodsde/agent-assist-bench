"""Deployment smoke/integration tests (Task 20.4).

Validates that deployment type settings flow correctly through the entire
pipeline: Settings → create_context → Runner → SQLite → Export → Report.

Also verifies Terraform variable structure and deployment metrics flow.

Requirements: 3.3, 3.4, 11.4, 20.4
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from benchmark.agents.hermes import HermesAdapter
from benchmark.agents.openclaw import OpenClawAdapter
from benchmark.agents.registry import AgentRegistry
from benchmark.cli.wiring import AppContext, create_context
from benchmark.config.settings import Settings
from benchmark.evaluation.service import EvaluationService
from benchmark.export.daily import DailyExporter
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentType,
    Evaluation,
)
from benchmark.report.generator import ReportGenerator
from benchmark.runner.config import RunnerConfig
from benchmark.runner.engine import BenchmarkRunner, DeploymentResourceConfig
from benchmark.storage.manager import StorageManager

# ---------------------------------------------------------------------------
# Mock transport for agent HTTP endpoints
# ---------------------------------------------------------------------------

HERMES_RESPONSE = "Hermes: deployment smoke test response."
OPENCLAW_RESPONSE = "OpenClaw: deployment smoke test response."


def _deployment_transport() -> httpx.MockTransport:
    """Mock transport that returns deterministic responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/models" in url:
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        if "/chat/completions" in url:
            if ":8001" in url:
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": HERMES_RESPONSE}}],
                        "model": "hermes-vm",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                    },
                )
            if ":8002" in url:
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": OPENCLAW_RESPONSE}}],
                        "model": "openclaw-container",
                        "usage": {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                    },
                )
        return httpx.Response(404, text="Not found")

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_deployment_context(
    tmp_path: Path,
    *,
    hermes_deploy: DeploymentType = DeploymentType.VIRTUAL_MACHINE,
    openclaw_deploy: DeploymentType = DeploymentType.MANAGED_CONTAINER,
    hermes_cpu: float = 4.0,
    hermes_memory: float = 8192.0,
    hermes_cost: float = 0.45,
    openclaw_cpu: float = 2.0,
    openclaw_memory: float = 4096.0,
    openclaw_cost: float = 0.25,
) -> AppContext:
    """Build a fully-wired AppContext with configured deployment types and metrics."""
    db_path = tmp_path / "deploy_smoke.db"
    storage = StorageManager(db_path=str(db_path))
    await storage.initialize()

    transport = _deployment_transport()
    hermes_http = httpx.AsyncClient(transport=transport)
    openclaw_http = httpx.AsyncClient(transport=transport)

    hermes = HermesAdapter(endpoint="http://localhost:8001", api_key="key-h", client=hermes_http)
    openclaw = OpenClawAdapter(
        endpoint="http://localhost:8002", api_key="key-o", client=openclaw_http
    )

    registry = AgentRegistry()
    registry.register(hermes, hermes_deploy, "http://localhost:8001")
    registry.register(openclaw, openclaw_deploy, "http://localhost:8002")

    runner_config = RunnerConfig(
        execution_order=[
            ("hermes", hermes_deploy),
            ("openclaw", openclaw_deploy),
        ],
        delay_between_seconds=0.0,
        timeout_seconds=5.0,
    )

    deployment_configs = {
        "hermes": DeploymentResourceConfig(
            cpu_cores=hermes_cpu,
            memory_mb=hermes_memory,
            cost_per_hour=hermes_cost,
        ),
        "openclaw": DeploymentResourceConfig(
            cpu_cores=openclaw_cpu,
            memory_mb=openclaw_memory,
            cost_per_hour=openclaw_cost,
        ),
    }

    runner = BenchmarkRunner(
        registry=registry,
        storage=storage,
        config=runner_config,
        deployment_configs=deployment_configs,
    )

    exporter = DailyExporter(storage=storage, export_dir=tmp_path / "exports")
    report_generator = ReportGenerator(storage=storage)
    evaluation_service = EvaluationService(storage=storage)

    return AppContext(
        storage=storage,
        registry=registry,
        runner=runner,
        exporter=exporter,
        report_generator=report_generator,
        evaluation_service=evaluation_service,
    )


# ---------------------------------------------------------------------------
# Test 1: Deployment type flows through entire pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deployment_type_flows_through_pipeline(tmp_path: Path) -> None:
    """Set deployment types via settings, run benchmark, verify in executions/export/report."""
    ctx = await _build_deployment_context(tmp_path)
    try:
        # Step 1: Run a benchmark
        benchmark = Benchmark(
            source="cli",
            prompt="Deployment pipeline test",
            tags=["deployment-smoke"],
        )
        await ctx.storage.save_benchmark(benchmark)
        status = await ctx.runner.run(benchmark)
        assert status == BenchmarkStatus.COMPLETED

        # Step 2: Verify execution records have correct deployment_type
        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2

        hermes_ex = executions[0]
        assert hermes_ex.agent_name == "hermes"
        assert hermes_ex.deployment.deployment_type == DeploymentType.VIRTUAL_MACHINE
        assert hermes_ex.deployment.provider == "vm"

        openclaw_ex = executions[1]
        assert openclaw_ex.agent_name == "openclaw"
        assert openclaw_ex.deployment.deployment_type == DeploymentType.MANAGED_CONTAINER
        assert openclaw_ex.deployment.provider == "cloud"

        # Step 3: Verify export includes correct deployment_type
        today = datetime.now(UTC).date().isoformat()
        manifest = await ctx.exporter.export_day(today)
        assert manifest.execution_count == 2

        jsonl_path = next(f for f in manifest.files if f.endswith(".jsonl"))
        with open(jsonl_path) as f:
            record = json.loads(f.readline())

        export_execs = record["executions"]
        assert export_execs[0]["deployment"]["deployment_type"] == "vm"
        assert export_execs[1]["deployment"]["deployment_type"] == "managed_container"

        # Step 4: Verify report shows correct provider info
        # Need evaluation for report to include data
        evaluation = Evaluation(
            benchmark_id=benchmark.id,
            rating=4,
            preferred_agent="hermes",
            preferred_deployment=DeploymentType.VIRTUAL_MACHINE,
        )
        await ctx.evaluation_service.submit(evaluation)

        report = await ctx.report_generator.generate(today, today)
        assert "vm" in report
        assert "cloud" in report
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# Test 2: Settings environment variable wiring for deployment types
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_settings_deployment_type_env_vars(tmp_path: Path) -> None:
    """Validate BENCH_HERMES_DEPLOYMENT_TYPE and BENCH_OPENCLAW_DEPLOYMENT_TYPE
    propagate through create_context correctly.
    """
    env = {
        "BENCH_HERMES_API_KEY": "test-hermes-key",
        "BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine",
        "BENCH_OPENCLAW_API_KEY": "test-openclaw-key",
        "BENCH_OPENCLAW_DEPLOYMENT_TYPE": "managed_container",
        "BENCH_DB_PATH": str(tmp_path / "env_test.db"),
        "BENCH_DELAY_SECONDS": "0",
        "BENCH_TIMEOUT_SECONDS": "5",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        ctx = await create_context(settings)

    try:
        # Hermes registered as VM
        hermes = ctx.registry.get("hermes", DeploymentType.VIRTUAL_MACHINE)
        assert hermes is not None
        assert hermes.name == "hermes"

        # OpenClaw registered as managed container
        openclaw = ctx.registry.get("openclaw", DeploymentType.MANAGED_CONTAINER)
        assert openclaw is not None
        assert openclaw.name == "openclaw"

        # Runner config reflects deployment types
        assert ("hermes", DeploymentType.VIRTUAL_MACHINE) in ctx.runner._config.execution_order
        assert (
            "openclaw",
            DeploymentType.MANAGED_CONTAINER,
        ) in ctx.runner._config.execution_order
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# Test 3: Terraform variable structure validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_terraform_variable_structure() -> None:
    """Read .tfvars.example files (if they exist) and verify required keys.

    If no Terraform files exist, validate that Settings has all required
    deployment-related fields that would map to Terraform variables.
    """
    project_root = Path(__file__).parent.parent.parent
    tfvars_candidates = list(project_root.glob("**/*.tfvars.example"))
    tfvars_candidates += list(project_root.glob("**/terraform/**/*.tfvars"))

    # Validate that Settings defines the required deployment configuration fields
    required_settings_fields = {
        "hermes_deployment_type",
        "openclaw_deployment_type",
        "hermes_endpoint",
        "openclaw_endpoint",
        "hermes_cpu_cores",
        "hermes_memory_mb",
        "hermes_cost_per_hour",
        "openclaw_cpu_cores",
        "openclaw_memory_mb",
        "openclaw_cost_per_hour",
    }

    settings_fields = set(Settings.model_fields.keys())
    missing = required_settings_fields - settings_fields
    assert not missing, f"Settings is missing required deployment fields: {missing}"

    # If tfvars exist, check that agent deployment files have agent_name and resource-related keys
    # Exclude non-agent tfvars (like ACR registry config)
    agent_tfvars = [
        f
        for f in tfvars_candidates
        if "acr" not in str(f).lower() and "registry" not in str(f).lower()
    ]
    if agent_tfvars:
        # Keys that should be present in every agent tfvars file (infrastructure identity)
        required_tf_keys = {"agent_name", "region", "resource_group_name"}
        for tfvars_path in agent_tfvars:
            content = tfvars_path.read_text()
            for key in required_tf_keys:
                assert key in content, f"Required key '{key}' not found in {tfvars_path}"
            # Each file must have some form of port or size configuration
            assert "port" in content or "vm_size" in content or "cpu" in content, (
                f"No resource sizing key found in {tfvars_path}"
            )


# ---------------------------------------------------------------------------
# Test 4: Deployment metrics flow through runner → SQLite → export → report
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deployment_metrics_flow(tmp_path: Path) -> None:
    """Verify cpu_cores, memory_mb, estimated_infra_cost_usd flow through
    runner → SQLite → export → report.
    """
    ctx = await _build_deployment_context(
        tmp_path,
        hermes_cpu=8.0,
        hermes_memory=16384.0,
        hermes_cost=1.20,
        openclaw_cpu=4.0,
        openclaw_memory=8192.0,
        openclaw_cost=0.60,
    )
    try:
        benchmark = Benchmark(
            source="cli",
            prompt="Metrics flow test",
            tags=["metrics-smoke"],
        )
        await ctx.storage.save_benchmark(benchmark)
        status = await ctx.runner.run(benchmark)
        assert status == BenchmarkStatus.COMPLETED

        # --- Runner → SQLite ---
        executions = await ctx.storage.get_executions(benchmark.id)
        assert len(executions) == 2

        hermes_ex = executions[0]
        assert hermes_ex.deployment.cpu_cores == 8.0
        assert hermes_ex.deployment.memory_mb == 16384
        assert hermes_ex.deployment.estimated_infra_cost_usd is not None
        assert hermes_ex.deployment.estimated_infra_cost_usd > 0

        openclaw_ex = executions[1]
        assert openclaw_ex.deployment.cpu_cores == 4.0
        assert openclaw_ex.deployment.memory_mb == 8192
        assert openclaw_ex.deployment.estimated_infra_cost_usd is not None
        assert openclaw_ex.deployment.estimated_infra_cost_usd > 0

        # --- SQLite → Export ---
        today = datetime.now(UTC).date().isoformat()
        manifest = await ctx.exporter.export_day(today)

        jsonl_path = next(f for f in manifest.files if f.endswith(".jsonl"))
        with open(jsonl_path) as f:
            record = json.loads(f.readline())

        export_hermes = record["executions"][0]
        assert export_hermes["deployment"]["cpu_cores"] == 8.0
        assert export_hermes["deployment"]["memory_mb"] == 16384
        assert export_hermes["deployment"]["estimated_infra_cost_usd"] is not None
        assert export_hermes["deployment"]["estimated_infra_cost_usd"] > 0

        export_openclaw = record["executions"][1]
        assert export_openclaw["deployment"]["cpu_cores"] == 4.0
        assert export_openclaw["deployment"]["memory_mb"] == 8192
        assert export_openclaw["deployment"]["estimated_infra_cost_usd"] is not None

        # --- Export CSV includes metrics ---
        exec_csv_path = next(f for f in manifest.files if "executions" in f and f.endswith(".csv"))
        with open(exec_csv_path) as f:
            csv_content = f.read()
        assert "8.0" in csv_content  # hermes cpu_cores
        assert "16384" in csv_content  # hermes memory_mb
        assert "4.0" in csv_content  # openclaw cpu_cores
        assert "8192" in csv_content  # openclaw memory_mb

        # --- Export → Report ---
        evaluation = Evaluation(
            benchmark_id=benchmark.id,
            rating=5,
            preferred_agent="hermes",
            preferred_deployment=DeploymentType.VIRTUAL_MACHINE,
        )
        await ctx.evaluation_service.submit(evaluation)

        report = await ctx.report_generator.generate(today, today)
        assert isinstance(report, str)
        assert "Benchmark Report" in report
        # Report should have cost analysis section referencing infra costs
        assert "Cost Analysis" in report
    finally:
        await ctx.storage.close()


# ---------------------------------------------------------------------------
# Test 5: Deployment resource config integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deployment_resource_config_integration(tmp_path: Path) -> None:
    """Verify DeploymentResourceConfig fields are wired through create_context."""
    env = {
        "BENCH_HERMES_API_KEY": "test-key",
        "BENCH_HERMES_DEPLOYMENT_TYPE": "virtual_machine",
        "BENCH_HERMES_CPU_CORES": "8",
        "BENCH_HERMES_MEMORY_MB": "16384",
        "BENCH_HERMES_COST_PER_HOUR": "1.5",
        "BENCH_OPENCLAW_API_KEY": "test-key",
        "BENCH_OPENCLAW_DEPLOYMENT_TYPE": "managed_container",
        "BENCH_OPENCLAW_CPU_CORES": "4",
        "BENCH_OPENCLAW_MEMORY_MB": "8192",
        "BENCH_OPENCLAW_COST_PER_HOUR": "0.75",
        "BENCH_DB_PATH": str(tmp_path / "resource_config.db"),
        "BENCH_DELAY_SECONDS": "0",
        "BENCH_TIMEOUT_SECONDS": "5",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        ctx = await create_context(settings)

    try:
        # Verify deployment configs were built from settings
        assert ctx.runner._deployment_configs is not None
        assert "hermes" in ctx.runner._deployment_configs
        assert "openclaw" in ctx.runner._deployment_configs

        hermes_rc = ctx.runner._deployment_configs["hermes"]
        assert hermes_rc.cpu_cores == 8.0
        assert hermes_rc.memory_mb == 16384.0
        assert hermes_rc.cost_per_hour == 1.5

        openclaw_rc = ctx.runner._deployment_configs["openclaw"]
        assert openclaw_rc.cpu_cores == 4.0
        assert openclaw_rc.memory_mb == 8192.0
        assert openclaw_rc.cost_per_hour == 0.75
    finally:
        await ctx.storage.close()
