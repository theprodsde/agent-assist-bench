# 13 — Observability

*Status: To be detailed in Phase 0*

## Logging

- Structured JSON logging via structlog
- Request correlation IDs (benchmark_id)
- Log levels: DEBUG, INFO, WARNING, ERROR

## Metrics

- Per-execution timing (cold start, total latency, API latency)
- LLM token usage (prompt, completion, total)
- Estimated cost per execution
- Success/failure counts per agent-deployment pair

## Health Checks

- `GET /health` — System status, agent count, DB connectivity
- Agent-level health checks before execution

## No Prometheus/Grafana (v1)

SQLite + daily exports provide sufficient observability for single-user workloads.

---

→ Previous: [12 — Deployment Design](12-deployment-design.md)  
→ Next: [14 — Security](14-security.md)
