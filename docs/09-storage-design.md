# 09 — Storage Design

*Status: To be detailed in Phase 0*

## Overview

SQLite with WAL mode. See [ADR-0004](ADR/ADR-0004-sqlite-storage.md).

## Tables

- `benchmarks` — Request metadata and status
- `executions` — Agent execution results and metrics
- `evaluations` — Human quality assessments

## Schema

See the [design spec](../.kiro/specs/agent-assist-bench/design.md) for complete SQL schema with constraints and indexes.

## Export Strategy

See [ADR-0009](ADR/ADR-0009-daily-export.md).

---

→ Previous: [08 — Data Model](08-data-model.md)  
→ Next: [10 — Benchmark Methodology](10-benchmark-methodology.md)
