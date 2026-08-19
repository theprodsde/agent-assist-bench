# ADR-0004: SQLite Storage

**Status:** Accepted  
**Date:** 2026-07-30

## Context

AgentAssistBench requires persistent storage for benchmarks, execution results, evaluations, and metrics. The storage solution must support:

- Single-user workloads (one developer running benchmarks)
- Zero-configuration setup
- Easy backup and portability
- Sufficient query performance for daily operations
- Export capabilities for analysis

The project explicitly excludes distributed systems, multi-user authentication, and production-grade dashboards from v1 scope.

## Decision

SQLite is the primary storage engine for all benchmark data.

### Schema Overview

```sql
-- Three core tables
benchmarks      -- Benchmark requests and metadata
executions      -- Individual agent-deployment execution results
evaluations     -- Human quality assessments
```

### Key Properties

- **Single file** — Entire database is one file (`storage/benchmark.db`)
- **WAL mode** — Write-Ahead Logging for concurrent read access during writes
- **Indexes** — On frequently queried columns (status, created_at, benchmark_id)
- **JSON columns** — Complex nested data stored as JSON text (attachments, tool_calls)

### Storage Location

```
storage/
├── benchmark.db          # Primary SQLite database
└── exports/              # Daily JSONL/CSV exports
    └── 2026-07-30/
        ├── benchmarks_2026-07-30.jsonl
        ├── benchmarks_2026-07-30.csv
        ├── executions_2026-07-30.csv
        └── evaluations_2026-07-30.csv
```

## Consequences

### Positive

- Zero configuration — no server to install or manage
- Easy backup — copy one file
- Portable — works on any OS, any filesystem
- Sufficient for single-user workloads (thousands of benchmarks)
- Excellent read performance with proper indexes
- No network dependency for storage
- Atomic transactions guarantee data integrity

### Negative

- Single-writer limitation (one write at a time)
- Not suitable for multi-user concurrent access
- No built-in replication
- Large attachments (base64) may bloat the database file
- No streaming queries for very large result sets

### Mitigations

- WAL mode enables concurrent reads during writes
- Daily exports create immutable snapshots for analysis
- Large attachments should use URL references instead of inline base64
- Migration path to PostgreSQL documented if requirements change

## Alternatives Considered

1. **PostgreSQL** — Rejected for v1 because it requires a server, adds operational complexity, and is unnecessary for single-user workloads. Remains the upgrade path if multi-user support is needed.
2. **DuckDB** — Considered for analytical queries but rejected because SQLite has broader ecosystem support and the analytical needs are served by CSV/JSONL exports.
3. **File-based storage (JSON files)** — Rejected because it lacks query capabilities, indexing, and transactional safety.
4. **Redis** — Rejected because it's in-memory (not persistent by default), adds operational complexity, and solves a different problem (caching, not primary storage).

## References

- [SQLite Documentation](https://www.sqlite.org/docs.html)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [Appropriate Uses For SQLite](https://www.sqlite.org/whentouse.html)
