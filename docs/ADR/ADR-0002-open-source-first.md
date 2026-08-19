# ADR-0002: Open Source First

**Status:** Accepted  
**Date:** 2026-07-30

## Context

Reproducibility is a core principle of benchmarking. If others cannot reproduce your results, the benchmark has limited value. Many existing benchmarks require proprietary infrastructure, specific cloud accounts, or non-public datasets to run.

AgentAssistBench aims to be a flagship engineering project that demonstrates best practices. Open-source development aligns with this goal and enables community contributions.

## Decision

Everything required to reproduce the benchmark shall be publicly available except secrets (API keys, credentials).

This includes:

- Docker configurations
- Terraform modules
- SQLite schema and migrations
- Documentation (architecture, ADRs, RFCs)
- Benchmark runner source code
- Export formats and tooling
- Reports and analysis scripts

No proprietary infrastructure is required to run the benchmark. Commercial agents (if added) remain optional adapters — the core system functions without them.

### Repository Contents

```
agent-assist-bench/
├── docs/          # All documentation, ADRs, RFCs
├── infra/         # Terraform modules
├── docker/        # Dockerfiles and compose
├── benchmark/     # Runner, API, agents
├── storage/       # Schema, migrations
├── scripts/       # Utility scripts
├── tests/         # All test suites
└── README.md
```

## Consequences

### Positive

- Anyone can reproduce benchmark results
- Community can contribute agents, deployments, and improvements
- Demonstrates professional open-source engineering practices
- Transparency builds trust in benchmark results
- Enables educational content (blogs, videos)

### Negative

- Secrets management requires additional tooling (.env, vault)
- Must be careful not to commit credentials
- Open issues and PRs require maintenance effort
- Competitive advantage is reduced (anyone can fork)

## Alternatives Considered

1. **Private repository with published results** — Rejected because it undermines reproducibility
2. **Open-core model (free core, paid extensions)** — Rejected because it conflicts with the benchmark's purpose of unbiased evaluation
3. **Academic paper with code supplement** — Rejected because the project is engineering-focused, not research-focused

## References

- [GitHub Open Source Guide](https://opensource.guide/)
- [OpenTelemetry](https://opentelemetry.io/) — Example of documentation-first open-source
- [LangChain](https://github.com/langchain-ai/langchain) — Example of open-source AI tooling
