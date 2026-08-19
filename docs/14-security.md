# 14 — Security

*Status: To be detailed in Phase 0*

## Threat Model

Single-user, local-network deployment. No public internet exposure in v1.

## Authentication

- No authentication required (single-user)
- CORS restricted to localhost by default

## Secrets

- Agent API keys in environment variables (`.env`)
- Never committed to git
- Terraform state may contain sensitive values — excluded from git

## Data Privacy

- Benchmark prompts may contain sensitive information
- Exports treated as potentially sensitive
- SQLite file permissions restricted (0600)

## Network

- HTTPS for remote agent endpoints
- HTTP acceptable for local Docker (development only)
- No mutual TLS in v1

## Input Validation

- Pydantic models for all API inputs
- Parameterized SQL queries (no string interpolation)
- Rate limiting not required for v1

---

→ Previous: [13 — Observability](13-observability.md)  
→ Next: [15 — Testing Strategy](15-testing-strategy.md)
