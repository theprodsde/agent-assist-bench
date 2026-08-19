# AgentAssistBench Documentation

Welcome to the AgentAssistBench technical documentation.

This directory contains the complete engineering design for the project. The documentation is intended to be read in order—each document builds on the previous one.

---

## Reading Order

| # | Document | Description |
|---|----------|-------------|
| 00 | [Project Overview](00-project-overview.md) | What is AgentAssistBench and why does it exist |
| 01 | [Problem Statement](01-problem-statement.md) | The gap in current AI benchmarking |
| 02 | [Goals & Non-Goals](02-goals-and-non-goals.md) | What we will and will not build |
| 03 | [Functional Requirements](03-functional-requirements.md) | Every capability the system must have |
| 04 | [Non-Functional Requirements](04-non-functional-requirements.md) | Performance, reliability, security constraints |
| 05 | [System Architecture](05-system-architecture.md) | Component diagrams and data flow |
| 06 | [Sequence Diagrams](06-sequence-diagrams.md) | Interaction flows between components |
| 07 | [API Specification](07-api-specification.md) | REST API contracts |
| 08 | [Data Model](08-data-model.md) | Domain models and relationships |
| 09 | [Storage Design](09-storage-design.md) | SQLite schema and export strategy |
| 10 | [Benchmark Methodology](10-benchmark-methodology.md) | How benchmarks are designed and evaluated |
| 11 | [Agent Interface](11-agent-interface.md) | Agent abstraction and adapter pattern |
| 12 | [Deployment Design](12-deployment-design.md) | Docker, VM, and managed container strategy |
| 13 | [Observability](13-observability.md) | Logging, metrics, and tracing |
| 14 | [Security](14-security.md) | Threat model and mitigations |
| 15 | [Testing Strategy](15-testing-strategy.md) | Unit, integration, and property-based testing |
| 16 | [Roadmap](16-roadmap.md) | Development phases and milestones |

---

## Architecture Decision Records

Major technical decisions are documented as [ADRs](ADR/README.md).

## Requests for Comments

Design proposals under discussion live in [RFCs](RFC/README.md).

---

## Versioning

| Version | Milestone |
|---------|-----------|
| v0.1.0 | Architecture complete |
| v0.2.0 | Infrastructure (Terraform + Docker) |
| v0.3.0 | Benchmark Runner |
| v0.4.0 | Hermes integration |
| v0.5.0 | OpenClaw integration |
| v0.6.0 | SQLite + Metrics |
| v0.7.0 | Telegram connector |
| v0.8.0 | Discord connector |
| v0.9.0 | End-to-end benchmark |
| v1.0.0 | Stable release |

---

## Contributing

1. Read the documentation in order
2. Check existing ADRs before proposing architectural changes
3. Submit an RFC for new design proposals
4. Implementation follows design — no code without a reviewed spec
