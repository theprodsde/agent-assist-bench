# ADR-0008: Infrastructure as Code

**Status:** Accepted  
**Date:** 2026-07-30

## Context

AgentAssistBench deploys AI agents across multiple infrastructure configurations (local Docker, VMs, managed containers). These deployments must be:

- Reproducible across environments
- Version controlled alongside application code
- Documentable and auditable
- Destroyable and recreatable on demand

Manual portal-based deployment (clicking through cloud consoles) is incompatible with these requirements. It produces undocumented infrastructure that cannot be reproduced, version controlled, or reliably destroyed.

## Decision

All infrastructure provisioning uses Terraform. Portal-based deployment is not part of the supported workflow.

### Repository Structure

```
infra/
├── terraform/
│   ├── modules/
│   │   ├── vm/              # Generic VM module
│   │   └── container/       # Generic managed container module
│   ├── azure/
│   │   ├── vm/
│   │   ├── container/
│   │   └── networking/
│   ├── aws/
│   │   ├── vm/
│   │   ├── container/
│   │   └── networking/
│   └── gcp/
│       ├── vm/
│       ├── container/
│       └── networking/
├── environments/
│   ├── dev.tfvars
│   ├── staging.tfvars
│   └── prod.tfvars
└── README.md
```

### Principles

1. **Declarative** — Describe desired state, not steps to reach it
2. **Idempotent** — Running `terraform apply` multiple times produces the same result
3. **Modular** — Shared modules for common patterns, provider-specific implementations
4. **Parameterized** — Environment differences captured in `.tfvars`, not code
5. **State-aware** — Terraform state tracked remotely (not in git)

### Workflow

```
terraform init → terraform plan → review → terraform apply → verify
```

The cloud console is used only for:
- Verification after `apply`
- Troubleshooting when something goes wrong
- Initial account setup (one-time)

## Consequences

### Positive

- Infrastructure is reproducible by anyone with the right credentials
- Changes are version controlled and reviewable in PRs
- Documentation is implicit in the code
- Supports multi-cloud deployment (ADR-0006)
- Easy to tear down and recreate environments
- Cost control through `terraform destroy`

### Negative

- Learning curve for contributors unfamiliar with Terraform
- State management requires a backend (S3, Azure Blob, GCS)
- Some cloud features are difficult to express in Terraform
- Terraform provider bugs can block deployments
- Sensitive values in state require encryption

### Mitigations

- Clear documentation and examples in `infra/README.md`
- State backend documented as part of setup guide
- Provider versions pinned in `versions.tf`
- Sensitive outputs marked appropriately

## Alternatives Considered

1. **Manual portal deployment** — Rejected because it's not reproducible, not version controlled, and cannot be reliably documented
2. **Pulumi** — Considered for its Python support but rejected because Terraform has broader community adoption, more providers, and better documentation
3. **CloudFormation / ARM / Deployment Manager** — Rejected because they're cloud-specific, violating ADR-0006 (Cloud Neutral Design)
4. **Ansible** — Rejected because it's procedural (not declarative) and better suited for configuration management than infrastructure provisioning
5. **Docker-only (no cloud IaC)** — Rejected because the benchmark explicitly compares VM vs. container deployments, which requires cloud infrastructure

## References

- [Terraform Documentation](https://developer.hashicorp.com/terraform/docs)
- [Terraform Best Practices](https://www.terraform-best-practices.com/)
- [Infrastructure as Code (Kief Morris)](https://infrastructure-as-code.com/)
