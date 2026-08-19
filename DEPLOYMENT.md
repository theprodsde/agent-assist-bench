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

## Virtual Machine (Production)

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

Deploy to Azure Container Apps or Google Cloud Run for auto-scaling and HTTPS.

### Prerequisites

- Azure CLI or gcloud CLI
- Container registry (ACR, GCR)
- NVIDIA API key

### 1. Build and push images

```bash
docker build -t <registry>/hermes:latest -f docker/hermes/Dockerfile .
docker build -t <registry>/openclaw:latest -f docker/openclaw/Dockerfile .

docker push <registry>/hermes:latest
docker push <registry>/openclaw:latest
```

### 2. Deploy to ACA (Azure)

```bash
az containerapp create \
  --name hermes \
  --image <registry>/hermes:latest \
  --environment <env_name> \
  --ingress external \
  --target-port 8642 \
  --env-vars-file docker/hermes/.env
```

### 3. Get public endpoints

```bash
az containerapp show -n hermes --query properties.configuration.ingress.fqdn
```

### 4. Point benchmark at ACA

```env
BENCH_HERMES_ENDPOINT=https://hermes.<domain>.azurecontainerapps.io/v1
BENCH_OPENCLAW_ENDPOINT=https://openclaw.<domain>.azurecontainerapps.io/v1
```

### 5. Run benchmarks

```bash
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
