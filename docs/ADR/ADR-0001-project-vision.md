# ADR-0001: Project Vision

**Status:** Accepted  
**Date:** 2026-07-30

## Context

Existing AI benchmarks primarily evaluate language models or agents using synthetic datasets and predefined tasks. Examples include coding benchmarks (SWE-bench), browser benchmarks (WebArena, BrowserArena), and reasoning benchmarks (GAIA).

These benchmarks provide useful research metrics but often do not answer practical engineering questions such as:

- Which agent helps me most during daily work?
- Which deployment model is most cost-effective?
- Which agent provides the best browser automation?
- Which deployment is most reliable?
- Which solution should I keep running every day?

There is currently no open-source framework focused on answering those questions through continuous evaluation of real workloads.

## Decision

Develop AgentAssistBench as an open-source framework that evaluates AI assistants using naturally occurring day-to-day tasks.

The benchmark will initially focus on:

- Personal engineering workflows
- Real prompts from actual work
- Real browser usage
- Real cloud deployments
- Human evaluation of response quality

The benchmark is intended to assist deployment and agent selection rather than produce academic benchmark scores.

### Target Personas

- **Developer** — Wants to run the benchmark locally with Docker
- **Evaluator** — Wants to compare agents and deployments using daily workflows
- **Contributor** — Wants to add a new agent, deployment target, or cloud provider

## Consequences

### Positive

- Results reflect actual daily usage patterns
- Easier to extend with new agents and deployment types
- Better practical value for engineering decision-making
- Lower maintenance than maintaining synthetic benchmark datasets
- Produces content suitable for technical blogs and videos

### Negative

- Human evaluation introduces subjectivity
- Different users may obtain different rankings
- Results are less directly comparable with academic benchmarks
- Smaller scale than synthetic benchmarks (bounded by real usage)

## Alternatives Considered

1. **Use GAIA** — Rejected because it evaluates general AI reasoning, not daily engineering workflows
2. **Use WebArena** — Rejected because it focuses on browser tasks only, not the full assistant experience
3. **Use BrowserArena** — Same limitation as WebArena
4. **Create synthetic benchmark tasks** — Rejected because synthetic tasks do not accurately represent real daily engineering work

## References

- [GAIA Benchmark](https://huggingface.co/gaia-benchmark)
- [WebArena](https://webarena.dev/)
- [BrowserArena](https://github.com/web-arena-x/webarena)
- [SWE-bench](https://www.swebench.com/)
