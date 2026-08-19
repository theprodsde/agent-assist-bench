# 04 — Non-Functional Requirements

*Status: To be detailed in Phase 0*

## Performance

| Metric | Target | Notes |
|--------|--------|-------|
| API request acceptance | < 50ms | Validation + ID generation only |
| Single agent execution | < 300s | Configurable timeout |
| Full benchmark (4 agents) | < 20min | Including delays |
| Database read | < 10ms | SQLite with indexes |
| Database write | < 20ms | WAL mode |
| Daily export (100 benchmarks) | < 30s | File I/O bound |

## Reliability

- Benchmark execution continues if one agent fails (partial failure)
- SQLite transactions ensure data integrity
- Idempotent exports are safe to retry
- Background task failure does not crash the API

## Security

- No authentication required (single-user, local network)
- API keys stored in environment variables, never in code
- Input validation via Pydantic (parameterized queries)
- HTTPS for remote agent endpoints
- SQLite file permissions restricted (0600)

## Portability

- Runs on macOS, Linux, Windows (Docker)
- SQLite database is a single portable file
- No cloud-provider-specific dependencies in application code
- JSONL/CSV exports readable by any tool

## Maintainability

- Documentation-first development process
- Architecture Decision Records for major choices
- Modular component design (agent adapters, storage, export)
- Type-safe Python (mypy, Pydantic)
- Comprehensive test suite (unit, integration, property-based)

## Scalability (v1 bounds)

- Single-user workload
- Hundreds of benchmarks per day
- Thousands of benchmarks total in SQLite
- No horizontal scaling required

## Observability

- Structured JSON logging (structlog)
- Request correlation IDs
- Execution timing metrics per agent
- Health check endpoint for system status

---

→ Previous: [03 — Functional Requirements](03-functional-requirements.md)  
→ Next: [05 — System Architecture](05-system-architecture.md)
