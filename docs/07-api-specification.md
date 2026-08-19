# 07 — API Specification

*Status: To be detailed in Phase 0*

## Endpoints

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| POST | `/benchmarks` | Create benchmark | 202 |
| GET | `/benchmarks` | List benchmarks | 200 |
| GET | `/benchmarks/{id}` | Get benchmark details | 200 |
| GET | `/benchmarks/{id}/results` | Get execution results | 200 |
| POST | `/benchmarks/{id}/evaluation` | Submit evaluation | 201 |
| GET | `/health` | Health check | 200 |
| POST | `/export/{date}` | Trigger export | 200 |

## Request/Response contracts

See the [design spec](../.kiro/specs/agent-assist-bench/design.md) for complete Pydantic models and API contracts.

---

→ Previous: [06 — Sequence Diagrams](06-sequence-diagrams.md)  
→ Next: [08 — Data Model](08-data-model.md)
