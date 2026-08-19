# ADR-0009: Daily Export Strategy

**Status:** Accepted  
**Date:** 2026-07-30

## Context

Benchmark data accumulates in SQLite over time. While SQLite handles this well for operational queries, several use cases require data in different formats:

- **Analysis** — Data scientists prefer CSV for spreadsheet/pandas analysis
- **Archival** — Immutable snapshots preserve historical data regardless of database changes
- **Portability** — JSONL files can be processed by any language or tool
- **Backup** — Daily exports serve as an additional backup layer
- **Sharing** — Export files can be shared without sharing the entire database

Additionally, keeping the operational database compact improves query performance over time.

## Decision

Benchmark results remain in SQLite during execution. At the end of each day, data is exported as immutable snapshots.

### Export Format

Each day produces:

```
storage/exports/
└── 2026-07-30/
    ├── benchmarks_2026-07-30.jsonl    # Complete records (nested)
    ├── benchmarks_2026-07-30.csv      # Flat benchmark metadata
    ├── executions_2026-07-30.csv      # Flat execution results
    └── evaluations_2026-07-30.csv     # Flat evaluation data
```

### JSONL Format

One line per benchmark, containing the complete record with nested executions and evaluation:

```json
{"benchmark": {...}, "executions": [...], "evaluation": {...}}
```

### CSV Format

Flat tables for spreadsheet analysis:

- `benchmarks.csv` — id, source, prompt, status, created_at, completed_at
- `executions.csv` — id, benchmark_id, agent_name, deployment_type, total_latency_ms, success
- `evaluations.csv` — id, benchmark_id, rating, preferred_agent, notes

### Trigger Mechanism

- **Primary:** Cron job or scheduled task (daily at midnight)
- **Secondary:** Manual trigger via API (`POST /export/{date}`)
- **Property:** Idempotent — re-running for the same date overwrites existing files

### Export Manifest

Each export produces a manifest for verification:

```python
class ExportManifest:
    date: str
    exported_at: datetime
    files: list[str]
    benchmark_count: int
    execution_count: int
    evaluation_count: int
```

## Consequences

### Positive

- Immutable daily snapshots preserve historical data
- Multiple formats serve different analysis needs
- SQLite database stays compact (old data can be archived)
- JSONL is machine-readable and streamable
- CSV is human-readable and spreadsheet-compatible
- Easy to share exports without database access
- Idempotent exports are safe to retry

### Negative

- Slight data duplication (data exists in both SQLite and exports)
- Requires disk space for accumulated exports
- Export timing may miss benchmarks completed near midnight
- No real-time export (daily granularity only)

### Mitigations

- Exports are small (text data, no binary attachments)
- Old exports can be compressed or moved to cold storage
- Export uses `created_at` date, not completion date, for consistency
- Manual export API provides on-demand capability

## Alternatives Considered

1. **No export (SQLite only)** — Rejected because SQLite files are difficult to analyze with standard data tools and don't provide immutable snapshots
2. **Real-time streaming (Kafka/Kinesis)** — Rejected because it adds massive infrastructure complexity for a single-user system
3. **PostgreSQL with materialized views** — Rejected because it contradicts ADR-0004 (SQLite) and adds operational overhead
4. **Weekly/monthly exports** — Rejected because daily granularity better matches the "daily engineering workflow" philosophy
5. **Parquet format** — Considered for analytical efficiency but rejected because CSV/JSONL are more universally accessible and the data volume doesn't warrant columnar storage

## References

- [JSON Lines Format](https://jsonlines.org/)
- [RFC 4180 — CSV Format](https://www.rfc-editor.org/rfc/rfc4180)
- [Data Lake Best Practices](https://aws.amazon.com/big-data/datalakes-and-analytics/)
