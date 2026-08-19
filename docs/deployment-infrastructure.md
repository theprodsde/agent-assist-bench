# Deployment Infrastructure

This guide explains how to deploy AgentAssistBench agents on virtual machines using Terraform and configure the benchmark runner to use VM endpoints.

## Overview

AgentAssistBench supports three deployment types for each agent:

| Deployment Type     | Environment Variable Value | Description                          |
|---------------------|----------------------------|--------------------------------------|
| Local Docker        | `local_docker`             | Agent running in local Docker container |
| Virtual Machine     | `virtual_machine`          | Agent running on a cloud VM          |
| Managed Container   | `managed_container`        | Agent running in managed container service (e.g. Azure Container Apps) |

The benchmark runner is deployment-agnostic. It receives an endpoint URL and a deployment type, and records this metadata with each execution. No runner code changes are needed when switching between deployment types.

## Deploying Agents on VMs with Terraform

### Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.5.0
- Cloud provider credentials configured (e.g. `az login` for Azure)
- SSH key pair for VM access

### Directory Structure

```
terraform/vm/
├── main.tf                    # Provider-neutral VM resource declarations
├── variables.tf               # Input variables
├── outputs.tf                 # Endpoint URL, health check URL, metadata
├── cloud-init.tpl             # VM initialization script template
├── hermes.tfvars.example      # Example values for Hermes VM
└── openclaw.tfvars.example    # Example values for OpenClaw VM
```

### Deploying Hermes

1. Copy and customize the example variables file:

```bash
cd terraform/vm
cp hermes.tfvars.example hermes.tfvars
# Edit hermes.tfvars with your actual values
```

2. Initialize and apply:

```bash
terraform init
terraform plan -var-file=hermes.tfvars
terraform apply -var-file=hermes.tfvars
```

3. Note the outputs:

```bash
terraform output endpoint_url
# => http://<public-ip>:8001

terraform output health_check_url
# => http://<public-ip>:8001/health
```

### Deploying OpenClaw

Same process with the OpenClaw variables file:

```bash
cp openclaw.tfvars.example openclaw.tfvars
terraform plan -var-file=openclaw.tfvars
terraform apply -var-file=openclaw.tfvars
```

### Switching Cloud Providers

The Terraform module uses Azure (`azurerm`) as its reference implementation. To deploy on AWS or GCP:

1. Replace the `provider` block in `main.tf` with the target provider
2. Replace Azure-specific resource types with equivalents (e.g. `aws_instance`, `google_compute_instance`)
3. Keep the same variable names and output contract — the benchmark runner only reads the outputs

The variable interface and output structure remain stable across providers.

## Configuring the Benchmark Runner

### Environment Variables

After deploying VMs, point the benchmark runner at the VM endpoints:

```bash
# Agent endpoints — set to the Terraform output endpoint_url values
export BENCH_HERMES_ENDPOINT="http://<hermes-vm-ip>:8001"
export BENCH_OPENCLAW_ENDPOINT="http://<openclaw-vm-ip>:8002"

# Deployment types — tells the runner what infrastructure each agent uses
export BENCH_HERMES_DEPLOYMENT_TYPE="virtual_machine"
export BENCH_OPENCLAW_DEPLOYMENT_TYPE="virtual_machine"

# API keys (required for agent authentication)
export BENCH_HERMES_API_KEY="your-hermes-api-key"
export BENCH_OPENCLAW_API_KEY="your-openclaw-api-key"
```

Or use a `.env` file:

```env
BENCH_HERMES_ENDPOINT=http://10.0.1.4:8001
BENCH_OPENCLAW_ENDPOINT=http://10.0.1.5:8002
BENCH_HERMES_DEPLOYMENT_TYPE=virtual_machine
BENCH_OPENCLAW_DEPLOYMENT_TYPE=virtual_machine
BENCH_HERMES_API_KEY=sk-hermes-prod-key
BENCH_OPENCLAW_API_KEY=sk-openclaw-prod-key
```

### Valid Deployment Type Values

The `BENCH_<AGENT>_DEPLOYMENT_TYPE` environment variables accept:

- `local_docker` (default) — agent running in local Docker
- `virtual_machine` or `vm` — agent running on a cloud VM
- `managed_container` — agent running in a managed container service

### Mixed Deployments

You can run agents on different deployment types simultaneously:

```bash
export BENCH_HERMES_DEPLOYMENT_TYPE="virtual_machine"
export BENCH_OPENCLAW_DEPLOYMENT_TYPE="local_docker"
```

The runner records deployment metadata with each execution, enabling cost and latency comparisons across deployment types in reports.

## Health Check Verification

Before running benchmarks, verify your VM-deployed agents are reachable:

```bash
# Check Hermes health
curl -f http://<hermes-vm-ip>:8001/health

# Check OpenClaw health
curl -f http://<openclaw-vm-ip>:8002/health
```

The benchmark runner also performs a health check before each execution and records cold-start latency. If a health check fails, the execution proceeds but `cold_start_ms` is recorded as null.

## Secrets Management

API keys are never hardcoded in Terraform state or configuration files:

- The `api_key_secret_ref` variable stores a reference to a Key Vault secret (e.g. Azure Key Vault URI)
- The VM retrieves the actual secret value at runtime using managed identity or instance metadata
- The benchmark runner reads API keys from environment variables or `.env` files only

## Deploying Agents on Azure Container Apps (ACA)

ACA is the recommended deployment for AgentAssistBench. It provides HTTPS endpoints with automatic TLS, HTTP-based autoscaling, and zero infrastructure management.

### Architecture: Separate Resource Groups

Each agent lives in its own resource group for isolation:

```
┌────────────────────────────┐    ┌────────────────────────────┐
│  rg-hermes (Resource Group)│    │  rg-openclaw (Resource Grp) │
│                            │    │                            │
│  hermes-env (Environment)  │    │  openclaw-env (Environment)│
│  hermes-ca  (Container App)│    │  openclaw-ca  (Container App)│
│  hermes-law (Log Analytics)│    │  openclaw-law (Log Analytics)│
│                            │    │                            │
│  Endpoint:                 │    │  Endpoint:                 │
│  https://hermes-ca.*.io    │    │  https://openclaw-ca.*.io  │
│  Scale: 1→10 (HTTP)        │    │  Scale: 1→10 (HTTP)        │
└────────────────────────────┘    └────────────────────────────┘
```

This gives you:
- Independent lifecycle management (update Hermes without touching OpenClaw)
- Separate billing visibility
- Isolated RBAC and networking
- Independent scaling behavior

### Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.5.0
- `az login` (Azure credentials)
- Container images pushed to a registry (e.g. Azure Container Registry)

### Deploying Hermes

```bash
cd terraform/aca
cp hermes.tfvars.example hermes.tfvars
# Edit: set your container_image and api_key_secret_ref

terraform init
terraform apply -var-file=hermes.tfvars
```

Get the endpoint:

```bash
terraform output endpoint_url
# → https://hermes-ca.eastus.azurecontainerapps.io
```

### Deploying OpenClaw

```bash
cp openclaw.tfvars.example openclaw.tfvars
# Edit: set your container_image and api_key_secret_ref

terraform apply -var-file=openclaw.tfvars
```

Get the endpoint:

```bash
terraform output endpoint_url
# → https://openclaw-ca.eastus.azurecontainerapps.io
```

### Autoscaling (HTTP-based, 1→10)

The module uses HTTP concurrent-request scaling by default:

| Setting | Default | Effect |
|---------|---------|--------|
| `min_replicas` | 1 | Always one replica ready (no cold start) |
| `max_replicas` | 10 | Scales up to 10 under load |
| `scale_concurrent_requests` | "10" | Add replica when >10 concurrent requests/replica |

When the benchmark runner sends requests sequentially, one replica handles everything. Under load (e.g., multiple concurrent Telegram/Discord inputs), ACA spins up replicas automatically.

Set `min_replicas=0` for scale-to-zero if you want cost savings when idle (introduces 5-15s cold start for the first request — captured as `cold_start_ms` in benchmark metrics).

### How Hermes/OpenClaw Run in ACA

Your agent container just needs to:
1. Listen on the configured port (default 8000)
2. Expose `POST /chat/completions` (OpenAI-compatible endpoint)
3. Expose `GET /health` for readiness/liveness probes
4. Read `AGENT_API_KEY` from environment for authentication

ACA injects the API key as an environment variable from the secret store. The container doesn't need to know about Azure.

### Minimal .tfvars Example

```hcl
agent_name          = "hermes"
resource_group_name = "rg-hermes"
container_image     = "myregistry.azurecr.io/hermes:latest"
container_port      = 8001
api_key_secret_ref  = "your-api-key"
region              = "eastus"
```

Everything else uses defaults: 1 CPU, 2Gi memory, scale 1→10.

### Wiring to the Benchmark Runner

After both agents are deployed:

```bash
export BENCH_HERMES_ENDPOINT=$(cd terraform/aca && terraform output -raw endpoint_url)
export BENCH_HERMES_DEPLOYMENT_TYPE=managed_container
export BENCH_HERMES_API_KEY="your-hermes-key"

export BENCH_OPENCLAW_ENDPOINT="https://openclaw-ca.eastus.azurecontainerapps.io"
export BENCH_OPENCLAW_DEPLOYMENT_TYPE=managed_container
export BENCH_OPENCLAW_API_KEY="your-openclaw-key"
```

Or in `.env`:

```env
BENCH_HERMES_ENDPOINT=https://hermes-ca.eastus.azurecontainerapps.io
BENCH_OPENCLAW_ENDPOINT=https://openclaw-ca.eastus.azurecontainerapps.io
BENCH_HERMES_DEPLOYMENT_TYPE=managed_container
BENCH_OPENCLAW_DEPLOYMENT_TYPE=managed_container
BENCH_HERMES_API_KEY=sk-hermes-prod
BENCH_OPENCLAW_API_KEY=sk-openclaw-prod
```

### Verifying the Deployment

```bash
# Health checks
curl -f https://hermes-ca.eastus.azurecontainerapps.io/health
curl -f https://openclaw-ca.eastus.azurecontainerapps.io/health

# Run a benchmark
aab run "What is dependency injection?"
aab status
```

### Destroying Infrastructure

Each agent is destroyed independently:

```bash
cd terraform/aca
terraform destroy -var-file=hermes.tfvars   # destroys rg-hermes
terraform destroy -var-file=openclaw.tfvars  # destroys rg-openclaw
```

---

## Destroying VM Infrastructure

To tear down deployed VMs:

```bash
cd terraform/vm
terraform destroy -var-file=hermes.tfvars
terraform destroy -var-file=openclaw.tfvars
```
