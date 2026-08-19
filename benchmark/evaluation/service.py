"""Evaluation business logic service.

Validates all preconditions before persisting an evaluation.
Follows DIP: accepts StorageManager as a dependency.
Follows SRP: handles evaluation validation only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from benchmark.evaluation.exceptions import (
    BenchmarkNotCompletedError,
    BenchmarkNotFoundError,
    EvaluationConflictError,
    EvaluationImmutableError,
    InvalidPreferredAgentError,
)
from benchmark.models.domain import BenchmarkStatus, Evaluation

if TYPE_CHECKING:
    from benchmark.storage.manager import StorageManager

logger = structlog.get_logger(__name__)

_EVALUABLE_STATUSES = frozenset({BenchmarkStatus.COMPLETED, BenchmarkStatus.PARTIALLY_FAILED})


class EvaluationService:
    """Validates and submits evaluations for completed benchmarks.

    Business rules enforced:
      - Benchmark must exist (Req 6.2)
      - Benchmark must be COMPLETED or PARTIALLY_FAILED (Req 6.3)
      - One evaluation per benchmark (Req 6.4)
      - preferred_agent must match an executed agent (Req 6.5)
      - Evaluations are immutable once submitted (Req 6.6)
    """

    def __init__(self, storage: StorageManager) -> None:
        self._storage = storage

    async def submit(self, evaluation: Evaluation) -> Evaluation:
        """Validate preconditions and persist evaluation.

        Args:
            evaluation: The evaluation to submit.

        Returns:
            The persisted evaluation (unchanged).

        Raises:
            BenchmarkNotFoundError: Benchmark does not exist.
            BenchmarkNotCompletedError: Benchmark status is not terminal-success.
            EvaluationConflictError: Evaluation already exists for benchmark.
            InvalidPreferredAgentError: preferred_agent not in executed agents.
        """
        benchmark_id = evaluation.benchmark_id

        # Req 6.2: Benchmark must exist
        benchmark = await self._storage.get_benchmark(benchmark_id)
        if benchmark is None:
            await logger.ainfo(
                "evaluation_rejected_benchmark_not_found",
                benchmark_id=benchmark_id,
            )
            raise BenchmarkNotFoundError(benchmark_id)

        # Req 6.3: Status must be COMPLETED or PARTIALLY_FAILED
        if benchmark.status not in _EVALUABLE_STATUSES:
            await logger.ainfo(
                "evaluation_rejected_benchmark_not_completed",
                benchmark_id=benchmark_id,
                status=str(benchmark.status),
            )
            raise BenchmarkNotCompletedError(benchmark_id, str(benchmark.status))

        # Req 6.4: No duplicate evaluations
        existing = await self._storage.get_evaluation(benchmark_id)
        if existing is not None:
            await logger.ainfo(
                "evaluation_rejected_duplicate",
                benchmark_id=benchmark_id,
                existing_evaluation_id=existing.id,
            )
            raise EvaluationConflictError(benchmark_id, existing.id)

        # Req 6.5: preferred_agent must match an executed agent
        if evaluation.preferred_agent is not None:
            executions = await self._storage.get_executions(benchmark_id)
            executed_agents = list({e.agent_name for e in executions})
            if evaluation.preferred_agent not in executed_agents:
                await logger.ainfo(
                    "evaluation_rejected_invalid_preferred_agent",
                    benchmark_id=benchmark_id,
                    preferred_agent=evaluation.preferred_agent,
                    available_agents=executed_agents,
                )
                raise InvalidPreferredAgentError(evaluation.preferred_agent, executed_agents)

        # All checks passed — persist
        await self._storage.save_evaluation(evaluation)
        await logger.ainfo(
            "evaluation_submitted",
            evaluation_id=evaluation.id,
            benchmark_id=benchmark_id,
            rating=evaluation.rating,
        )
        return evaluation

    async def guard_immutable(self, evaluation_id: str) -> None:
        """Reject any modification or deletion attempt on an existing evaluation.

        Call this method before any update/delete operation.

        Raises:
            EvaluationImmutableError: Always, if the evaluation exists.
        """
        await logger.ainfo(
            "evaluation_modification_rejected",
            evaluation_id=evaluation_id,
        )
        raise EvaluationImmutableError(evaluation_id)
