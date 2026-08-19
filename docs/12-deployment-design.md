# 12 — Deployment Design

*Status: To be detailed in Phase 0*

## Overview

Cloud neutral deployment abstraction. See [ADR-0006](ADR/ADR-0006-cloud-neutral-design.md).

## Deployment Types

| Type | Description |
|------|-------------|
| `local_docker` | Docker containers on developer machine |
| `vm` | Virtual machine (any cloud) |
| `managed_container` | Managed container service (any cloud) |

## Infrastructure

Terraform-based provisioning. See [ADR-0008](ADR/ADR-0008-infrastructure-as-code.md).

## Local Development

Docker Compose for running the full stack locally.

---

→ Previous: [11 — Agent Interface](11-agent-interface.md)  
→ Next: [13 — Observability](13-observability.md)
