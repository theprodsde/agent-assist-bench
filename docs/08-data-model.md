# 08 — Data Model

*Status: To be detailed in Phase 0*

## Domain Models

- Benchmark
- Execution
- Evaluation
- Attachment
- DeploymentMetrics
- LLMMetrics
- ExecutionResult
- ExportManifest

## Enums

- BenchmarkStatus: pending, running, completed, partially_failed, failed
- InputType: text, image, audio, document, url
- DeploymentType: local_docker, vm, managed_container

See the [design spec](../.kiro/specs/agent-assist-bench/design.md) for complete Pydantic model definitions and validation rules.

---

→ Previous: [07 — API Specification](07-api-specification.md)  
→ Next: [09 — Storage Design](09-storage-design.md)
