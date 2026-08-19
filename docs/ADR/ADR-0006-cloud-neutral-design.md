# ADR-0006: Cloud Neutral Design

**Status:** Accepted  
**Date:** 2026-07-30

## Context

AgentAssistBench deploys AI agents across different infrastructure configurations to compare performance. The benchmark must support multiple cloud providers without coupling the core logic to any specific provider's services.

Cloud providers offer equivalent compute primitives under different names:

| Concept | Azure | AWS | GCP |
|---------|-------|-----|-----|
| Virtual Machine | Azure VM | EC2 | Compute Engine |
| Managed Container | Azure Container Apps | ECS/Fargate | Cloud Run |
| Container Registry | ACR | ECR | Artifact Registry |

The benchmark should measure deployment type differences (VM vs. container), not cloud provider differences.

## Decision

The benchmark abstracts deployment types rather than cloud providers.

### Supported Deployment Categories

| Category | Description | Use Case |
|----------|-------------|----------|
| `local_docker` | Docker containers on developer machine | Development and testing |
| `vm` | Virtual machine (any cloud or bare metal) | Traditional deployment |
| `managed_container` | Managed container service (any cloud) | Serverless/managed deployment |

### Abstraction Layer

```python
class DeploymentType(str, Enum):
    LOCAL_DOCKER = "local_docker"
    VIRTUAL_MACHINE = "vm"
    MANAGED_CONTAINER = "managed_container"
```

Cloud providers implement these abstractions through Terraform modules:

```
infra/terraform/
├── azure/
│   ├── vm/
│   └── container/
├── aws/
│   ├── vm/
│   └── container/
└── gcp/
    ├── vm/
    └── container/
```

### Design Rules

1. Core benchmark logic never references a specific cloud provider
2. Agent adapters connect via HTTP — they don't know where they're deployed
3. Infrastructure concerns live exclusively in `infra/` directory
4. Switching clouds requires only Terraform changes, not code changes

## Consequences

### Positive

- Support for Azure, GCP, AWS, or local environments without changing benchmark logic
- Easy to add new cloud providers (implement Terraform modules)
- Benchmark results compare deployment patterns, not vendor lock-in
- Developers can run everything locally without cloud accounts
- Infrastructure is interchangeable at the Terraform layer

### Negative

- Cannot leverage cloud-specific optimizations (e.g., Azure-specific networking)
- Terraform modules must be maintained per provider
- Some deployment features are provider-specific and not abstractable
- Initial implementation may target a single cloud (pragmatism)

### Mitigations

- Start with one cloud provider, add others incrementally
- Provider-specific optimizations can be added as optional Terraform variables
- Agent adapters communicate over standard HTTP — no provider SDK dependency

## Alternatives Considered

1. **Azure-only** — Rejected because it limits reproducibility and creates vendor lock-in
2. **Kubernetes everywhere** — Rejected because Kubernetes is explicitly excluded from v1 scope (ADR-0001 non-goals) and adds unnecessary complexity for single-user benchmarks
3. **Abstract cloud SDK** — Rejected because agents communicate over HTTP; no need to abstract SDKs in application code
4. **Multi-cloud from day one** — Rejected as impractical; design for it, implement incrementally

## References

- [Terraform Provider Registry](https://registry.terraform.io/browse/providers)
- [The Twelve-Factor App](https://12factor.net/) — Environment parity principle
- [Cloud Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/patterns/)
