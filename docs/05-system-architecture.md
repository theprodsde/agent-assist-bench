# 05 — System Architecture

*Status: To be detailed in Phase 0*

## Overview

This document will contain the complete system architecture including component diagrams, data flow, and infrastructure topology.

## Components

1. **API Gateway** — FastAPI HTTP entry point
2. **Benchmark Runner** — Sequential execution orchestrator
3. **Agent Abstraction Layer** — Uniform interface for all agents
4. **Agent Adapters** — Hermes, OpenClaw implementations
5. **Storage Manager** — SQLite persistence layer
6. **Daily Exporter** — JSONL/CSV snapshot generation
7. **Input Channels** — Telegram, Discord, CLI connectors

## Architecture Diagram

See the [design spec](../.kiro/specs/agent-assist-bench/design.md) for the complete Mermaid diagram.

## Design Decisions

- [ADR-0003: Sequential Execution](ADR/ADR-0003-sequential-execution.md)
- [ADR-0004: SQLite Storage](ADR/ADR-0004-sqlite-storage.md)
- [ADR-0006: Cloud Neutral Design](ADR/ADR-0006-cloud-neutral-design.md)
- [ADR-0007: Agent Abstraction](ADR/ADR-0007-agent-abstraction.md)

---

→ Previous: [04 — Non-Functional Requirements](04-non-functional-requirements.md)  
→ Next: [06 — Sequence Diagrams](06-sequence-diagrams.md)
