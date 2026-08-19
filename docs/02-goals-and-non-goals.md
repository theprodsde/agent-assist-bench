# 02 — Goals & Non-Goals

## Primary Goal

Build an open-source framework that evaluates AI assistants using naturally occurring daily tasks.

## Secondary Goals

| # | Goal | Rationale |
|---|------|-----------|
| 1 | Compare multiple AI agents | Determine which agent is best for specific task types |
| 2 | Compare deployment strategies | Measure performance differences between Docker, VM, and managed containers |
| 3 | Compare operational cost | Understand per-request cost across configurations |
| 4 | Measure infrastructure performance | Cold start, latency, reliability metrics |
| 5 | Preserve benchmark history | Daily exports enable longitudinal analysis |
| 6 | Produce reproducible benchmark reports | Anyone with the same setup gets comparable results |
| 7 | Enable anyone to reproduce the benchmark | Open-source, documented, IaC-provisioned |

## Non-Goals (v1)

The following are explicitly excluded from the first release:

| Exclusion | Reason |
|-----------|--------|
| Kubernetes | Unnecessary complexity for single-user workloads |
| Redis | No caching requirements in v1 |
| PostgreSQL | SQLite is sufficient (ADR-0004) |
| Vector databases | No semantic search requirements |
| Distributed execution | Single machine is sufficient |
| Multi-user authentication | Single-user benchmark |
| Academic benchmark leaderboards | Not the project's purpose |
| Automatic quality scoring | Human evaluation is the design choice (ADR-0005) |
| Production-grade dashboards | Exports + analysis tools are sufficient |
| Grafana / Prometheus | Overkill for single-user observability |
| Kafka / RabbitMQ | No streaming requirements |
| Real-time notifications | Daily export is the feedback loop |

## Guiding Principles

### 1. Real Workloads Over Synthetic Benchmarks

Every benchmark originates from a real user interaction. No artificial benchmark dataset is required.

### 2. Open Source First

Everything required to reproduce the benchmark is public except credentials. (ADR-0002)

### 3. Cloud Neutral

The benchmark targets deployment patterns (Docker, VM, Container) rather than cloud providers. (ADR-0006)

### 4. Agent Neutral

The benchmark does not favor a specific agent. All agents implement the same interface. (ADR-0007)

### 5. Human Evaluation

Response quality is evaluated by the user after execution. The framework collects data but does not decide which response is "better." (ADR-0005)

### 6. Infrastructure as Code

Infrastructure is provisioned using Terraform. The cloud console is used only for verification. (ADR-0008)

### 7. Keep It Simple

Prefer simple solutions until proven insufficient.

Initial stack:
- SQLite (not PostgreSQL)
- FastAPI (not Django)
- Docker (not Kubernetes)
- Terraform (not Pulumi)
- JSONL exports (not Kafka streams)

## Feature Prioritization

| Priority | Feature | Phase |
|----------|---------|-------|
| Must Have | Sequential benchmark execution | 3 |
| Must Have | SQLite storage | 6 |
| Must Have | Human evaluation | 8 |
| Must Have | Daily JSONL/CSV export | 6 |
| Must Have | Hermes adapter | 4 |
| Must Have | OpenClaw adapter | 5 |
| Must Have | Docker deployment | 1 |
| Should Have | Terraform VM deployment | 1 |
| Should Have | Terraform managed container | 1 |
| Should Have | Telegram connector | 7 |
| Should Have | Discord connector | 7 |
| Could Have | CLI tool | 7 |
| Could Have | Markdown reports | 9 |
| Won't Have (v1) | Parallel execution | — |
| Won't Have (v1) | LLM-as-judge scoring | — |
| Won't Have (v1) | Multi-user support | — |

---

→ Previous: [01 — Problem Statement](01-problem-statement.md)  
→ Next: [03 — Functional Requirements](03-functional-requirements.md)
