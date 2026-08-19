# 15 — Testing Strategy

*Status: To be detailed in Phase 0*

## Testing Pyramid

| Layer | Tool | Purpose |
|-------|------|---------|
| Unit | pytest | Component logic in isolation |
| Integration | pytest + temp SQLite | Components working together |
| Property-Based | hypothesis | Invariant verification |
| E2E | httpx + TestClient | Full API workflow |

## Key Test Areas

- **Benchmark Runner:** Sequential ordering, delays, timeouts, error handling
- **Storage Manager:** CRUD operations, filtering, transactions
- **Agent Adapters:** Request/response translation, error parsing
- **Daily Exporter:** File format correctness, idempotency
- **API Models:** Pydantic validation rules

## Property-Based Testing

Correctness properties verified with hypothesis:
- Sequential execution ordering
- Status/failure consistency
- ULID sortability
- Evaluation uniqueness
- Export idempotency

## Coverage Target

- > 80% line coverage for core modules
- 100% coverage for data validation logic

---

→ Previous: [14 — Security](14-security.md)  
→ Next: [16 — Roadmap](16-roadmap.md)
