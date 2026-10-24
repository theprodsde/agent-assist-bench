# Deployment Guide

AgentAssistBench supports three deployment models for running Hermes and OpenClaw agents.

## Local Docker (Development)

Fastest way to get started for testing and local development.

### 1. Copy environment templates

```bash
cp docker/hermes/.env.example docker/hermes/.env
cp docker/openclaw/.env.example docker/openclaw/.env
```

### 2. Add NVIDIA API key (optional)

If you want to run the real agent stack, add your NVIDIA key to both `.env` files:

```env
MODEL_API_KEY=nvapi-xxxx
```

Get a free key at https://console.nvidia.com/

### 3. Start containers

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml up -d --build
```

### 4. Verify health

```bash
curl http://localhost:8001/health    # Hermes
curl http://localhost:8002/health    # OpenClaw
```

### 5. Run a benchmark

```bash
aab run "Explain machine learning in one sentence"
```

### 6. Stop the stack

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml down
```

---

## Virtual Machine

> ⚠️ **Not recommended.** The `terraform/vm` config is a reference template: its cloud-init
> runs `docker run <image>` without any registry login or pull source, and the NSG opens
> SSH and the agent port to the internet. Prefer the [Managed Container](#managed-container-recommended-for-production)
> path below, which is validated and cheaper (scale-to-zero).

Deploy agents to a VM (e.g., Azure VM, AWS EC2) with Terraform.

### Prerequisites

- Terraform configured
- Azure/AWS credentials
- NVIDIA API key

### 1. Configure Terraform

Edit `terraform/vm/terraform.tfvars`:

```hcl
location = "eastus"
vm_size  = "Standard_D4s_v3"
hermes_nvidia_api_key = "nvapi-xxxx"
openclaw_nvidia_api_key = "nvapi-xxxx"
```

### 2. Deploy

```bash
cd terraform/vm
terraform init
terraform apply
```

### 3. Point benchmark at VM

Edit `.env`:

```env
BENCH_HERMES_ENDPOINT=http://<VM_IP>:8001/v1
BENCH_OPENCLAW_ENDPOINT=http://<VM_IP>:8002/v1
```

### 4. Run benchmarks

```bash
aab run "Your test prompt"
```

---

## Managed Container (Recommended for Production)

Deploy to Azure Container Apps (ACA) with the Terraform module in `terraform/aca`.
You get HTTPS ingress, health probes, HTTP autoscaling, managed-identity image
pulls (no registry passwords), and optional scale-to-zero so idle agents cost
almost nothing.

### Prerequisites

- Terraform >= 1.5 and Azure CLI (`az login`)
- An Azure Container Registry (see `terraform/acr`, or `az acr create`)
- NVIDIA API key (or your own model backend)

### 1. Build and push images

```bash
az acr login --name <registry>

docker build -t <registry>.azurecr.io/hermes:latest -f docker/hermes/Dockerfile .
docker build -t <registry>.azurecr.io/openclaw:latest -f docker/openclaw/Dockerfile .

docker push <registry>.azurecr.io/hermes:latest
docker push <registry>.azurecr.io/openclaw:latest
```

### 2. Configure and deploy each agent

Each agent is an independent Terraform stack (separate resource group and
state). Fill in the example vars — including `acr_id` so the app's managed
identity can pull your image, and either a literal `api_key` or a Key Vault
reference (`api_key_key_vault_secret_id` + `key_vault_id`):

```bash
cd terraform/aca
cp hermes.tfvars.example hermes.tfvars     # edit values
terraform init
terraform apply -var-file=hermes.tfvars

cp openclaw.tfvars.example openclaw.tfvars # edit values
terraform apply -var-file=openclaw.tfvars -state=openclaw.tfstate
```

Set `min_replicas = 0` (the default) for scale-to-zero — cheapest, but the
first request after idle pays a cold start. Use `min_replicas = 1` if you
want consistent latency numbers in your benchmarks.

### 3. Point benchmark at ACA

```bash
export BENCH_HERMES_ENDPOINT=$(terraform output -raw endpoint_url)/v1
export BENCH_HERMES_DEPLOYMENT_TYPE=managed_container
# repeat for openclaw with -state=openclaw.tfstate
```

### 4. Verify and run

```bash
curl -i "$(terraform output -raw health_check_url)"
aab run "Your test prompt"
```

---

## Configuration Reference

### Environment Variables

All agents respect these variables (via `.env` or `docker/*/env`):

```env
# LLM Backend
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=nvapi-xxxx  # NVIDIA API key

# Hermes-specific
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=your-bearer-token

# OpenClaw-specific
AGENT_API_KEY=your-bearer-token
```

### Benchmark Runner Configuration

Set in root `.env`:

```env
BENCH_HERMES_ENDPOINT=http://localhost:8001/v1
BENCH_OPENCLAW_ENDPOINT=http://localhost:8002/v1
BENCH_HERMES_API_KEY=your-hermes-token
BENCH_OPENCLAW_API_KEY=your-openclaw-token
BENCH_DELAY_SECONDS=2.0
BENCH_TIMEOUT_SECONDS=300
BENCH_DB_PATH=storage/benchmark.db
BENCH_EXPORT_DIR=storage/exports
BENCH_LOG_LEVEL=INFO
```

---

## Health Checks

Every agent must respond on `/health` with a `200 OK`:

```bash
curl -i http://localhost:8001/health
# HTTP/1.1 200 OK
```

And `/v1/models` (used by adapters):

```bash
curl http://localhost:8001/v1/models
# { "object": "list", "data": [] }
```

---

## Troubleshooting

### Container won't start

Check logs:

```bash
docker compose logs hermes
docker compose logs openclaw
```

### Health check fails

Wait 30+ seconds for initialization:

```bash
watch -n 1 'curl -s http://localhost:8001/health'
```

### API requests timeout

Check NVIDIA key is valid and container has internet:

```bash
docker exec hermes-agent curl https://integrate.api.nvidia.com/v1/models
```

### Port already in use

Edit `docker-compose.yml`:

```yaml
ports:
  - "9001:8642"  # Use 9001 instead of 8001
```

Update `.env`:

```env
BENCH_HERMES_ENDPOINT=http://localhost:9001/v1
```
