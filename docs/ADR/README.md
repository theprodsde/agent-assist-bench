# Architecture Decision Records

AgentAssistBench uses Architecture Decision Records (ADRs) to document significant technical and architectural decisions.

An ADR captures:

- The problem being solved
- The context and constraints
- The decision made
- Alternatives considered
- Consequences (positive and negative)

The objective is to preserve engineering reasoning so contributors understand **why** a design exists, not just what was built.

---

## ADR Status Lifecycle

```
Proposed → Accepted → [Deprecated | Superseded]
```

- **Proposed** — Under discussion, not yet implemented
- **Accepted** — Decision made, guides implementation
- **Deprecated** — No longer relevant (system changed)
- **Superseded** — Replaced by a newer ADR

---

## Current Decisions

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-0001](ADR-0001-project-vision.md) | Project Vision | Accepted | 2026-07-30 |
| [ADR-0002](ADR-0002-open-source-first.md) | Open Source First | Accepted | 2026-07-30 |
| [ADR-0003](ADR-0003-sequential-execution.md) | Sequential Execution | Accepted | 2026-07-30 |
| [ADR-0004](ADR-0004-sqlite-storage.md) | SQLite Storage | Accepted | 2026-07-30 |
| [ADR-0005](ADR-0005-human-evaluation.md) | Human Evaluation | Accepted | 2026-07-30 |
| [ADR-0006](ADR-0006-cloud-neutral-design.md) | Cloud Neutral Design | Accepted | 2026-07-30 |
| [ADR-0007](ADR-0007-agent-abstraction.md) | Agent Abstraction | Accepted | 2026-07-30 |
| [ADR-0008](ADR-0008-infrastructure-as-code.md) | Infrastructure as Code | Accepted | 2026-07-30 |
| [ADR-0009](ADR-0009-daily-export.md) | Daily Export Strategy | Accepted | 2026-07-30 |
| [ADR-0010](ADR-0010-real-workload-benchmark.md) | Real Workload Benchmarking | Accepted | 2026-07-30 |

---

## Creating a New ADR

Every major architectural decision must be documented before implementation.

1. Copy the template below
2. Assign the next sequential number
3. Use a descriptive kebab-case filename: `ADR-XXXX-short-title.md`
4. Submit as part of a PR or RFC discussion
5. Update this index when the ADR is accepted

### Template

```markdown
# ADR-XXXX: Title

**Status:** Proposed | Accepted | Deprecated | Superseded  
**Date:** YYYY-MM-DD  
**Supersedes:** (if applicable)  
**Superseded by:** (if applicable)

## Context

What is the issue that motivates this decision?

## Decision

What is the change that we're proposing or have agreed to implement?

## Consequences

### Positive
- ...

### Negative
- ...

## Alternatives Considered

1. Alternative A — why rejected
2. Alternative B — why rejected

## References

- Links to RFCs, issues, or external resources
```

---

## When to Write an ADR

Write an ADR when a decision:

- Affects the system architecture
- Introduces or removes a technology
- Changes data flow or storage strategy
- Impacts multiple components
- Would be difficult or costly to reverse
- Warrants explanation for future contributors
