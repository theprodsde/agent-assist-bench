"""Custom exceptions for evaluation business rules.

Each exception maps to a specific requirement validation failure,
providing clear error messages for CLI/API consumers.
"""


class BenchmarkNotFoundError(Exception):
    """Raised when evaluation targets a non-existent benchmark (Req 6.2)."""

    def __init__(self, benchmark_id: str) -> None:
        self.benchmark_id = benchmark_id
        super().__init__(f"Benchmark not found: {benchmark_id}")


class BenchmarkNotCompletedError(Exception):
    """Raised when benchmark status is not COMPLETED or PARTIALLY_FAILED (Req 6.3)."""

    def __init__(self, benchmark_id: str, status: str) -> None:
        self.benchmark_id = benchmark_id
        self.status = status
        super().__init__(
            f"Benchmark '{benchmark_id}' has status '{status}'. "
            f"Only benchmarks with status COMPLETED or PARTIALLY_FAILED accept evaluations."
        )


class EvaluationConflictError(Exception):
    """Raised when an evaluation already exists for the benchmark (Req 6.4)."""

    def __init__(self, benchmark_id: str, existing_evaluation_id: str) -> None:
        self.benchmark_id = benchmark_id
        self.existing_evaluation_id = existing_evaluation_id
        super().__init__(
            f"Evaluation already exists for benchmark '{benchmark_id}' "
            f"(evaluation_id='{existing_evaluation_id}'). "
            f"Only one evaluation per benchmark is allowed."
        )


class InvalidPreferredAgentError(Exception):
    """Raised when preferred_agent doesn't match any executed agent (Req 6.5)."""

    def __init__(self, preferred_agent: str, available_agents: list[str]) -> None:
        self.preferred_agent = preferred_agent
        self.available_agents = available_agents
        super().__init__(
            f"Preferred agent '{preferred_agent}' does not match any executed agent. "
            f"Available agents: {', '.join(available_agents) or 'none'}"
        )


class EvaluationImmutableError(Exception):
    """Raised when modification or deletion of an evaluation is attempted (Req 6.6)."""

    def __init__(self, evaluation_id: str) -> None:
        self.evaluation_id = evaluation_id
        super().__init__(
            f"Evaluation '{evaluation_id}' is immutable once submitted. "
            f"Modifications and deletions are not allowed."
        )
