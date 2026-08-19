"""Runner configuration for benchmark execution.

Defines RunnerConfig which controls execution order, delays, and timeouts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmark.models.domain import DeploymentType


@dataclass(frozen=True)
class RunnerConfig:
    """Configuration for a benchmark execution run.

    Attributes:
        execution_order: Ordered list of (agent_name, deployment_type) pairs
            to execute sequentially.
        delay_between_seconds: Seconds to wait between consecutive executions.
            Applied after the first execution (not before it).
            Valid range: 0.0 to 60.0. Default: 2.0.
        timeout_seconds: Maximum seconds to wait for a single agent execution.
            Valid range: 1 to 3600. Default: 300.
    """

    execution_order: list[tuple[str, DeploymentType]] = field(default_factory=list)
    delay_between_seconds: float = 2.0
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        """Validate configuration ranges."""
        if not (0.0 <= self.delay_between_seconds <= 60.0):
            raise ValueError(
                f"delay_between_seconds must be 0.0-60.0, got {self.delay_between_seconds}"
            )
        if not (1 <= self.timeout_seconds <= 3600):
            raise ValueError(f"timeout_seconds must be 1-3600, got {self.timeout_seconds}")
