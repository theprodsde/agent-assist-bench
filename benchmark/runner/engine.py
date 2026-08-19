"""Benchmark Runner engine for sequential agent execution.

Orchestrates executing a benchmark request across configured agent-deployment
pairs, collecting timing metrics and handling errors gracefully.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from benchmark.agents.base import AgentAdapter, AgentRequest, AgentResponse
from benchmark.models.domain import (
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Execution,
    ExecutionResult,
)

if TYPE_CHECKING:
    from benchmark.agents.registry import AgentRegistry
    from benchmark.runner.config import RunnerConfig
    from benchmark.storage.manager import StorageManager

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeploymentResourceConfig:
    """Resource configuration for a single agent deployment.

    Holds CPU, memory, and cost-per-hour values used to populate deployment
    metrics and estimate per-execution infrastructure cost.
    """

    cpu_cores: float | None = None
    memory_mb: float | None = None
    cost_per_hour: float | None = None


class BenchmarkRunner:
    """Sequentially executes a benchmark across all agent-deployment pairs.

    Accepts AgentRegistry and StorageManager as constructor dependencies (DIP).
    Works with any AgentAdapter implementation (OCP).
    """

    def __init__(
        self,
        registry: AgentRegistry,
        storage: StorageManager,
        config: RunnerConfig,
        deployment_configs: dict[str, DeploymentResourceConfig] | None = None,
    ) -> None:
        self._registry = registry
        self._storage = storage
        self._config = config
        self._deployment_configs = deployment_configs or {}

    async def run(self, benchmark: Benchmark) -> BenchmarkStatus:
        """Execute benchmark sequentially across all configured pairs.

        Iterates through config.execution_order, applies delays between
        executions, and persists each result before moving to the next.
        Returns the final benchmark status.

        Req 2.1: Sequential execution in configured order.
        Req 2.2: Configurable delay between executions.
        Req 2.9: Persist each result before proceeding.
        """
        log = logger.bind(
            benchmark_id=benchmark.id,
            execution_order=[f"{name}:{dt}" for name, dt in self._config.execution_order],
        )
        log.info("benchmark_run_started")

        failures = 0
        total = len(self._config.execution_order)

        for i, (agent_name, deploy_type) in enumerate(self._config.execution_order):
            # Check if agent is registered (Req 2.6)
            agent = self._registry.get(agent_name, deploy_type)
            if agent is None:
                log.warning(
                    "agent_not_registered",
                    agent_name=agent_name,
                    deployment_type=str(deploy_type),
                )
                execution = self._make_skip_execution(benchmark.id, agent_name, deploy_type)
                await self._storage.save_execution(execution)
                failures += 1
                continue

            # Apply delay between executions, not before the first (Req 2.2)
            if i > 0 and self._config.delay_between_seconds > 0:
                log.debug(
                    "benchmark_execution_delay",
                    wait_seconds=self._config.delay_between_seconds,
                )
                await asyncio.sleep(self._config.delay_between_seconds)

            # Execute with timeout (Req 2.7)
            execution = await self._execute_with_timeout(
                benchmark, agent, agent_name, deploy_type, log
            )
            if not execution.success:
                failures += 1

            # Persist before next (Req 2.9)
            await self._storage.save_execution(execution)

        # Determine final status (Req 2.3, 2.4, 2.5)
        status = self._determine_status(failures, total)
        await self._storage.update_status(benchmark.id, status)

        log.info(
            "benchmark_run_completed",
            status=str(status),
            total=total,
            failures=failures,
        )
        return status

    async def _execute_with_timeout(
        self,
        benchmark: Benchmark,
        agent: AgentAdapter,
        agent_name: str,
        deploy_type: DeploymentType,
        log: structlog.stdlib.BoundLogger,
    ) -> Execution:
        """Execute a single agent with timeout enforcement."""
        try:
            execution = await asyncio.wait_for(
                self._execute_single(benchmark, agent, agent_name, deploy_type),
                timeout=self._config.timeout_seconds,
            )
            log.info(
                "agent_execution_completed",
                agent_name=agent_name,
                deployment_type=str(deploy_type),
                latency_ms=execution.deployment.total_latency_ms,
                success=execution.success,
            )
            if execution.result.errors:
                # Log only stable error labels/counts; response text and full
                # error strings remain unchanged in the execution record.
                log.warning(
                    "agent_execution_response_error",
                    benchmark_id=benchmark.id,
                    agent_name=agent_name,
                    deployment_type=str(deploy_type),
                    error_count=len(execution.result.errors),
                    error_types=[error.split(":", 1)[0] for error in execution.result.errors],
                )
            return execution
        except TimeoutError:
            log.error(
                "agent_execution_timeout",
                benchmark_id=benchmark.id,
                agent_name=agent_name,
                deployment_type=str(deploy_type),
                error_type="TimeoutError",
                error_message=(f"Execution exceeded {self._config.timeout_seconds}s timeout"),
            )
            return self._make_timeout_execution(benchmark.id, agent_name, deploy_type)
        except Exception as exc:
            log.error(
                "agent_execution_error",
                benchmark_id=benchmark.id,
                agent_name=agent_name,
                deployment_type=str(deploy_type),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return self._make_error_execution(benchmark.id, agent_name, deploy_type, exc)

    async def _execute_single(
        self,
        benchmark: Benchmark,
        agent: AgentAdapter,
        agent_name: str,
        deploy_type: DeploymentType,
    ) -> Execution:
        """Execute a single agent-deployment pair with timing metrics.

        Req 4.1: Measure total_latency_ms with monotonic clock.
        Req 4.2: Measure cold_start_ms via health check.
        Req 4.3: Handle health check failure gracefully.
        Req 4.6: Record started_at and completed_at as UTC.
        """
        started_at = datetime.now(UTC)

        # Measure cold start via health check (Req 4.2, 4.3)
        cold_start_ms = await self._measure_cold_start(agent)

        # Build the typed request without converting or dropping attachment data.
        # A fresh list prevents one adapter from mutating the benchmark-owned list
        # while preserving each full Attachment model for every configured agent.
        agent_request = AgentRequest(
            prompt=benchmark.prompt,
            attachments=list(benchmark.attachments),
            conversation_id=benchmark.conversation_id,
        )

        # Execute with timing (Req 4.1)
        exec_start = time.perf_counter_ns()
        response: AgentResponse = await agent.execute(agent_request)
        total_latency_ms = (time.perf_counter_ns() - exec_start) / 1_000_000

        completed_at = datetime.now(UTC)

        success = len(response.errors) == 0

        # Populate deployment resource metrics from config
        res_config = self._deployment_configs.get(agent_name)
        cpu_cores = res_config.cpu_cores if res_config else None
        memory_mb_val: int | None = (
            int(res_config.memory_mb) if res_config and res_config.memory_mb else None
        )

        # Calculate estimated infrastructure cost from latency and cost_per_hour
        estimated_infra_cost_usd: float | None = None
        if res_config and res_config.cost_per_hour is not None:
            estimated_infra_cost_usd = (total_latency_ms / 3_600_000) * res_config.cost_per_hour

        return Execution(
            benchmark_id=benchmark.id,
            agent_name=agent_name,
            agent_version=agent.version,
            deployment=DeploymentMetrics(
                provider=self._resolve_provider(deploy_type),
                deployment_type=deploy_type,
                cold_start_ms=cold_start_ms,
                total_latency_ms=total_latency_ms,
                cpu_cores=cpu_cores,
                memory_mb=memory_mb_val,
                estimated_infra_cost_usd=estimated_infra_cost_usd,
            ),
            llm=response.llm_metrics,
            result=ExecutionResult(
                raw_response=response.content,
                errors=response.errors,
            ),
            started_at=started_at,
            completed_at=completed_at,
            success=success,
        )

    async def _measure_cold_start(self, agent: AgentAdapter) -> float | None:
        """Measure cold start via health check. Returns None on failure (Req 4.3)."""
        try:
            health_start = time.perf_counter_ns()
            await agent.health_check()
            return (time.perf_counter_ns() - health_start) / 1_000_000
        except Exception:
            return None

    @staticmethod
    def _determine_status(failures: int, total: int) -> BenchmarkStatus:
        """Determine final benchmark status based on failure count.

        Req 2.3: 0 failures -> COMPLETED
        Req 2.4: mixed -> PARTIALLY_FAILED
        Req 2.5: all failures -> FAILED
        """
        if total == 0:
            return BenchmarkStatus.COMPLETED
        if failures == 0:
            return BenchmarkStatus.COMPLETED
        if failures == total:
            return BenchmarkStatus.FAILED
        return BenchmarkStatus.PARTIALLY_FAILED

    @staticmethod
    def _resolve_provider(deploy_type: DeploymentType) -> str:
        """Resolve provider name from deployment type."""
        mapping = {
            DeploymentType.LOCAL_DOCKER: "docker",
            DeploymentType.VIRTUAL_MACHINE: "vm",
            DeploymentType.MANAGED_CONTAINER: "cloud",
        }
        return mapping.get(deploy_type, "unknown")

    @staticmethod
    def _make_skip_execution(
        benchmark_id: str,
        agent_name: str,
        deploy_type: DeploymentType,
    ) -> Execution:
        """Create an execution record for a skipped (unregistered) agent."""
        now = datetime.now(UTC)
        return Execution(
            benchmark_id=benchmark_id,
            agent_name=agent_name,
            agent_version="unknown",
            deployment=DeploymentMetrics(
                provider=BenchmarkRunner._resolve_provider(deploy_type),
                deployment_type=deploy_type,
                cold_start_ms=None,
                total_latency_ms=0.01,  # Minimal positive value required by validator
            ),
            llm=None,
            result=ExecutionResult(
                raw_response="",
                errors=["Agent not registered"],
            ),
            started_at=now,
            completed_at=now,
            success=False,
        )

    @staticmethod
    def _make_timeout_execution(
        benchmark_id: str,
        agent_name: str,
        deploy_type: DeploymentType,
    ) -> Execution:
        """Create an execution record for a timed-out agent."""
        now = datetime.now(UTC)
        return Execution(
            benchmark_id=benchmark_id,
            agent_name=agent_name,
            agent_version="unknown",
            deployment=DeploymentMetrics(
                provider=BenchmarkRunner._resolve_provider(deploy_type),
                deployment_type=deploy_type,
                cold_start_ms=None,
                total_latency_ms=0.01,
            ),
            llm=None,
            result=ExecutionResult(
                raw_response="",
                errors=["Execution timed out"],
            ),
            started_at=now,
            completed_at=now,
            success=False,
        )

    @staticmethod
    def _make_error_execution(
        benchmark_id: str,
        agent_name: str,
        deploy_type: DeploymentType,
        exc: Exception,
    ) -> Execution:
        """Create an execution record for an agent that raised an exception."""
        now = datetime.now(UTC)
        return Execution(
            benchmark_id=benchmark_id,
            agent_name=agent_name,
            agent_version="unknown",
            deployment=DeploymentMetrics(
                provider=BenchmarkRunner._resolve_provider(deploy_type),
                deployment_type=deploy_type,
                cold_start_ms=None,
                total_latency_ms=0.01,
            ),
            llm=None,
            result=ExecutionResult(
                raw_response="",
                errors=[f"{type(exc).__name__}: {exc}"],
            ),
            started_at=now,
            completed_at=now,
            success=False,
        )
