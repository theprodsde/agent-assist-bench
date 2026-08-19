# Deployment Workflow

End-to-end guide: build containers → test locally → push to ACR → deploy to ACA → run benchmarks.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  NVIDIA API (integrate.api.nvidia.com/v1)                │
│  Model: nvidia/llama-3.1-nemotron-ultra-253b-v1          │
└───────────────────────────▲──────────────────────────────┘
                            │  LLM API calls
            ┌───────────────┼───────────────┐
            │               │               │
┌───────────┴────────┐  ┌──┴───────────────┐
│  Hermes Agent      │  │  OpenClaw Agent   │
│  (ACA: rg-hermes)  │  │  (ACA: rg-openclaw)│
│                    │  │                   │
│  NousResearch      │  │  openclaw/openclaw│
│  hermes-agent      │  │                   │
│  2 CPU / 4Gi       │  │  2 CPU / 4Gi      │
│  Scale: 1→10       │  │  Scale: 1→10      │
│  Port: 8001        │  │  Port: 8002       │
└────────┬───────────┘  └────────┬──────────┘
         │                       │
         └───────────┬───────────┘
                     │  OpenAI-compatible HTTP
         ┌───────────▼───────────┐
         │  Benchmark Runner     │
         │  (your machine)       │
         │                       │
         │  Measures:            │
         │  - Response quality   │
         │  - Latency/cold-start │
         │  - Cost per request   │
         │  - Autonomy/errors    │
         │                       │
         │  Weekly report →      │
         │  Which agent to keep? │
         └───────────────────────┘
```

Both agents:
- Use the same model (Nemotron-120B)
- Get the same resources (2 CPU, 4Gi)
- Have the same tool capabilities enabled (browser, code execution, web search)
- Run with maximum freedom and reasoning (no confirmation prompts)
- Have 1 instance always running (no cold start)

The only difference is the agent framework itself — how it reasons, plans, uses tools, and learns.

---

## Step 1: Set Up Environment Variables

### Agent .env files

```bash
cd docker/hermes
cp .env.example .env

cd ../openclaw
cp .env.example .env
```

Edit both `.env` files:

```env
# Same for both agents — the NVIDIA LLM backend
MODEL_NAME=nvidia/llama-3.1-nemotron-ultra-253b-v1
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=nvapi-YOUR-ACTUAL-NVIDIA-KEY

# Auth keys — YOU choose these values (any random string)
# Generate with: openssl rand -hex 32
AGENT_API_KEY=a1b2c3d4e5f6...your-random-string...
SIGNING_KEY=f6e5d4c3b2a1...another-random-string...
```

### What are AGENT_API_KEY and SIGNING_KEY?

| Variable | What it is | Who sets it | Where it goes |
|----------|-----------|-------------|---------------|
| `AGENT_API_KEY` | A password you make up | You (any random string) | Agent `.env` AND benchmark runner's `BENCH_HERMES_API_KEY` / `BENCH_OPENCLAW_API_KEY` |
| `SIGNING_KEY` | An HMAC secret you make up | You (any random string) | Agent `.env` AND benchmark runner's `BENCH_SIGNING_KEY` |

They're not provided by anyone — **you generate them yourself**. They just need to match between the agent container and the benchmark runner.

Generate them:
```bash
# Generate a random AGENT_API_KEY
openssl rand -hex 32
# → e.g. 4a8f2c1b9e7d6f3a5c8b4e2d1f9a7c6b3e5d8f2a4c7b9e1d6f3a5c8b4e2d1f9a

# Generate a random SIGNING_KEY
openssl rand -hex 32
# → e.g. 7b3e5d8f2a4c9b1e6d3f5a8c4b2e7d1f9a6c3b5e8d2f4a7c1b9e6d3f5a8c4b2e
```

---

## Step 2: Test Locally with Docker

```bash
# Build and start both agents
docker compose -f docker/docker-compose.test.yml up --build

# In another terminal — verify health
curl http://localhost:8001/health   # Hermes
curl http://localhost:8002/health   # OpenClaw

# Test a real request to Hermes
curl -X POST http://localhost:8001/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_AGENT_API_KEY" \
  -d '{"messages":[{"role":"user","content":"What is dependency injection? Give me a Python example."}]}'

# Test a real request to OpenClaw
curl -X POST http://localhost:8002/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_AGENT_API_KEY" \
  -d '{"messages":[{"role":"user","content":"What is dependency injection? Give me a Python example."}]}'

# Run a benchmark against local containers
export BENCH_HERMES_ENDPOINT=http://localhost:8001
export BENCH_OPENCLAW_ENDPOINT=http://localhost:8002
export BENCH_HERMES_API_KEY=your-agent-api-key
export BENCH_OPENCLAW_API_KEY=your-agent-api-key
export BENCH_SIGNING_KEY=your-signing-key
export BENCH_DELAY_SECONDS=0

aab run "Write a Python function that reads a CSV and handles encoding errors"
aab status
```

Once both agents respond correctly locally, proceed to cloud deployment.

---

## Step 3: Deploy Azure Container Registry (ACR)

ACR stores your Docker images. Deploy once, push updates anytime.

```bash
cd terraform/acr
cp acr.tfvars.example acr.tfvars
# Edit: set your preferred registry_name (must be globally unique, alphanumeric)

terraform init
terraform apply -var-file=acr.tfvars

# Note the login server:
terraform output login_server
# → agentbenchacr.azurecr.io
```

---

## Step 4: Build and Push Images to ACR

```bash
# Login to ACR
az acr login --name agentbenchacr

# Build directly in ACR (no local Docker needed for this step):
az acr build --registry agentbenchacr \
  --image hermes:latest \
  --file docker/hermes/Dockerfile .

az acr build --registry agentbenchacr \
  --image openclaw:latest \
  --file docker/openclaw/Dockerfile .

# Verify images exist:
az acr repository list --name agentbenchacr
# → ["hermes", "openclaw"]
```

Note: the checked-in local Docker stack now builds Hermes from the local Dockerfile, so the local Docker workflow is self-contained. OpenClaw is still pulled from GHCR in the override stack, but the Hermes dependency on GHCR has been removed.

---

## Step 5: Deploy to ACA (Separate Resource Groups)

Each agent gets its own resource group, environment, and auto-scaling.

### Deploy Hermes

```bash
cd terraform/aca
cp hermes.tfvars.example hermes.tfvars
# Edit: set api_key_secret_ref to your AGENT_API_KEY value

terraform init
terraform apply -var-file=hermes.tfvars

# Get the endpoint:
terraform output endpoint_url
# → https://hermes-ca.eastus.azurecontainerapps.io
```

### Deploy OpenClaw

```bash
cp openclaw.tfvars.example openclaw.tfvars
# Edit: set api_key_secret_ref to your AGENT_API_KEY value

terraform apply -var-file=openclaw.tfvars

# Get the endpoint:
terraform output endpoint_url
# → https://openclaw-ca.eastus.azurecontainerapps.io
```

### Verify deployments

```bash
curl https://hermes-ca.eastus.azurecontainerapps.io/health
curl https://openclaw-ca.eastus.azurecontainerapps.io/health
```

---

## Step 6: Wire Benchmark Runner to ACA Endpoints

Create a `.env` file in the project root:

```env
# Endpoints from terraform output
BENCH_HERMES_ENDPOINT=https://hermes-ca.eastus.azurecontainerapps.io
BENCH_OPENCLAW_ENDPOINT=https://openclaw-ca.eastus.azurecontainerapps.io

# Deployment type metadata
BENCH_HERMES_DEPLOYMENT_TYPE=managed_container
BENCH_OPENCLAW_DEPLOYMENT_TYPE=managed_container

# Auth keys (must match what you put in the agent .env files)
BENCH_HERMES_API_KEY=your-agent-api-key
BENCH_OPENCLAW_API_KEY=your-agent-api-key
BENCH_SIGNING_KEY=your-signing-key

# Resource tracking (matches ACA config — 2 CPU / 4Gi for both)
BENCH_HERMES_CPU_CORES=2.0
BENCH_HERMES_MEMORY_MB=4096
BENCH_OPENCLAW_CPU_CORES=2.0
BENCH_OPENCLAW_MEMORY_MB=4096

# Runner settings
BENCH_DELAY_SECONDS=2
BENCH_TIMEOUT_SECONDS=120
```

---

## Step 7: Run Benchmarks for a Week

```bash
# Submit daily tasks through the benchmark
aab run "Summarize this article and extract key points: [paste article]"
aab run "Write a Python script that monitors a directory for new CSV files"
aab run "Debug this error: TypeError: cannot unpack non-sequence NoneType"
aab run "Create a REST API design for a todo app with auth"

# Check status
aab status

# At end of week — evaluate responses
aab evaluate

# Generate comparison report
aab report --days 7
```

The weekly report shows per-category:
- Win rate (which agent you preferred)
- Average latency
- Average cost
- Error/failure rate
- Recommendations per task category

---

## ACA Configuration Notes

| Setting | Hermes | OpenClaw | Why |
|---------|--------|----------|-----|
| Resource Group | `rg-hermes` | `rg-openclaw` | Isolated billing/RBAC |
| CPU | 2.0 | 2.0 | Fair comparison |
| Memory | 4Gi | 4Gi | Fair comparison |
| Min replicas | 1 | 1 | No cold start |
| Max replicas | 10 | 10 | Scale under load |
| Scale trigger | 10 concurrent req | 10 concurrent req | Same behavior |

---

## Troubleshooting

### Agent not responding
```bash
# Check ACA logs
az containerapp logs show --name hermes-ca --resource-group rg-hermes --follow
az containerapp logs show --name openclaw-ca --resource-group rg-openclaw --follow
```

### Auth failures (401)
- Verify AGENT_API_KEY in agent .env matches BENCH_HERMES_API_KEY in runner .env
- Verify SIGNING_KEY matches BENCH_SIGNING_KEY (or both are empty to disable)

### NVIDIA API errors
- Verify MODEL_API_KEY starts with `nvapi-`
- Check NVIDIA API dashboard for rate limits/quota

### Updating agent images
```bash
# Rebuild and push new version
az acr build --registry agentbenchacr --image hermes:latest --file docker/hermes/Dockerfile .

# ACA pulls the new image on next revision (or force restart):
az containerapp revision restart --name hermes-ca --resource-group rg-hermes
```
