"""Markdown comparison report generator.

Produces per-category comparison reports for agent-deployment pairs,
including win rates, average cost, average latency, and recommendations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import structlog

from benchmark.storage.manager import BenchmarkFilters, StorageManager

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass
class _PairStats:
    """Accumulator for a single agent-deployment pair within a category."""

    wins: int = 0
    total: int = 0
    successful: int = 0
    failures: int = 0
    cost_sum: float = 0.0
    cost_count: int = 0
    latency_sum: float = 0.0
    latency_count: int = 0
    infra_cost_sum: float = 0.0
    infra_cost_count: int = 0
    providers: set[str] = field(default_factory=set)


class ReportGenerator:
    """Generates Markdown comparison reports from evaluated benchmark data.

    Accepts a StorageManager dependency for data access (DIP).
    """

    def __init__(self, storage: StorageManager) -> None:
        self._storage = storage

    async def generate(self, start_date: str, end_date: str) -> str:
        """Generate a Markdown report for the given ISO 8601 date range."""
        logger.info("report_generation_started", start_date=start_date, end_date=end_date)

        categories: dict[str, dict[str, _PairStats]] = defaultdict(lambda: defaultdict(_PairStats))
        execution_errors: list[tuple[str, str, str, list[str]]] = []
        total_evaluated = 0

        benchmarks = await self._storage.list_benchmarks(
            BenchmarkFilters(date_from=start_date, date_to=f"{end_date}T23:59:59", limit=0)
        )

        for benchmark in benchmarks:
            evaluation = await self._storage.get_evaluation(benchmark.id)
            if evaluation is None:
                continue
            executions = await self._storage.get_executions(benchmark.id)
            if not executions:
                continue

            total_evaluated += 1
            tags = benchmark.tags if benchmark.tags else ["uncategorized"]

            for tag in tags:
                for ex in executions:
                    pair_key = f"{ex.agent_name}/{ex.deployment.deployment_type.value}"
                    stats = categories[tag][pair_key]
                    stats.total += 1
                    if ex.success:
                        stats.successful += 1
                    else:
                        stats.failures += 1
                        execution_errors.append(
                            (benchmark.id, tag, pair_key, list(ex.result.errors))
                        )
                    # A failed execution is never a human-preferred successful
                    # result, but its metrics remain in the same aggregates as
                    # before so existing cost/latency behavior is unchanged.
                    # preferred_deployment is optional (the CLI only collects
                    # the agent name); when absent, the agent name alone wins.
                    if (
                        ex.success
                        and evaluation.preferred_agent == ex.agent_name
                        and (
                            evaluation.preferred_deployment is None
                            or evaluation.preferred_deployment == ex.deployment.deployment_type
                        )
                    ):
                        stats.wins += 1
                    if ex.llm and ex.llm.estimated_cost_usd is not None:
                        stats.cost_sum += ex.llm.estimated_cost_usd
                        stats.cost_count += 1
                    if ex.deployment.estimated_infra_cost_usd is not None:
                        stats.infra_cost_sum += ex.deployment.estimated_infra_cost_usd
                        stats.infra_cost_count += 1
                    stats.latency_sum += ex.deployment.total_latency_ms
                    stats.latency_count += 1
                    stats.providers.add(ex.deployment.provider)

        report = self._render(start_date, end_date, total_evaluated, categories, execution_errors)
        logger.info(
            "report_generation_completed",
            start_date=start_date,
            end_date=end_date,
            category_count=len(categories),
        )
        return report

    def _render(
        self,
        start_date: str,
        end_date: str,
        total_evaluated: int,
        categories: dict[str, dict[str, _PairStats]],
        execution_errors: list[tuple[str, str, str, list[str]]],
    ) -> str:
        """Render gathered statistics into a Markdown string."""
        lines: list[str] = [
            f"# Benchmark Report: {start_date} to {end_date}",
            "",
            f"**{total_evaluated} Benchmarks Evaluated**",
            "",
        ]
        recommendations: list[tuple[str, str, float, float, str]] = []

        for category in sorted(categories.keys()):
            pairs = categories[category]
            sample_size = max(s.total for s in pairs.values()) if pairs else 0
            low_sample = sample_size < 5

            lines.append(f"## {category}")
            lines.append("")
            if low_sample:
                lines.append(
                    f"> ⚠️ Warning: fewer than 5 evaluated benchmarks in this"
                    f" category (n={sample_size}). Results may not be reliable."
                )
                lines.append("")
            lines.append("| Agent | Win Rate | Avg Cost | Avg Latency | Failed |")
            lines.append("|-------|----------|----------|-------------|--------|")

            best: tuple[str, float, float, str] | None = None
            for pair_key in sorted(pairs.keys()):
                s = pairs[pair_key]
                wr = round((s.wins / s.total * 100) if s.total > 0 else 0.0, 2)
                # Per-request LLM cost is typically sub-cent; 6dp keeps it visible.
                ac = f"${s.cost_sum / s.cost_count:.6f}/req" if s.cost_count > 0 else "—"
                al = round((s.latency_sum / s.latency_count) if s.latency_count > 0 else 0.0, 2)
                lines.append(f"| {pair_key} | {wr}% | {ac} | {al}ms | {s.failures} |")
                provider_str = ", ".join(sorted(s.providers)) if s.providers else "unknown"
                if (
                    not low_sample
                    and s.successful > 0
                    and (best is None or wr > best[1] or (wr == best[1] and al < best[2]))
                ):
                    best = (pair_key, wr, al, provider_str)

            lines.append("")
            if best and not low_sample:
                recommendations.append((category, best[0], best[1], best[2], best[3]))

        # Cost Analysis section
        lines.append("## Cost Analysis")
        lines.append("")
        has_cost_data = any(
            s.infra_cost_count > 0 for pairs in categories.values() for s in pairs.values()
        )
        if has_cost_data:
            lines.append("| Agent | Category | Provider | Avg Infra Cost/Exec |")
            lines.append("|-------|----------|----------|---------------------|")
            for category in sorted(categories.keys()):
                pairs = categories[category]
                for pair_key in sorted(pairs.keys()):
                    s = pairs[pair_key]
                    if s.infra_cost_count > 0:
                        avg_infra = round(s.infra_cost_sum / s.infra_cost_count, 6)
                        provider_str = ", ".join(sorted(s.providers)) if s.providers else "unknown"
                        lines.append(f"| {pair_key} | {category} | {provider_str} | ${avg_infra} |")
        else:
            lines.append(
                "No infrastructure cost data available. Configure `BENCH_*_COST_PER_HOUR` to enable."
            )
        lines.append("")

        if execution_errors:
            lines.append("## Execution Errors")
            lines.append("")
            lines.append(
                "Failed executions are shown explicitly and are excluded from human-preference wins."
            )
            lines.append("")
            for benchmark_id, category, pair_key, errors in execution_errors:
                detail = (
                    "; ".join(errors) if errors else "execution failed without a reported error"
                )
                lines.append(f"- {benchmark_id} [{category}] {pair_key}: {detail}")
            lines.append("")

        lines.append("## Recommendations")
        lines.append("")
        if recommendations:
            lines.append("| Category | Best Agent | Win Rate | Avg Latency | Provider |")
            lines.append("|----------|------------|----------|-------------|----------|")
            for cat, agent, wr, lat, provider in recommendations:
                lines.append(f"| {cat} | {agent} | {wr}% | {lat}ms | {provider} |")
        else:
            lines.append("No categories have sufficient data for recommendations.")
        lines.append("")
        return "\n".join(lines)
