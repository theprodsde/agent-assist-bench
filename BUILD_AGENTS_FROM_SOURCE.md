# Building Real Agent Frameworks from Source

This guide explains how to build **Hermes** and **OpenClaw** agent frameworks from the external repository clones and run them in Docker containers for benchmarking.

## Architecture

```
Benchmark Runner (AgentAssistBench)
           ↓ (HTTP requests)
    ┌──────┴──────┐
    ▼             ▼
 Hermes Agent  OpenClaw Agent
 (Docker)      (Docker)
 Port 8001     Port 8002
```

Both agents expose OpenAI-compatible `/v1/chat/completions` endpoints.

## Prerequisites

- Docker and docker-compose installed
- External repositories cloned:
  - `external/hermes-agent/` (from https://github.com/nousresearch/hermes-agent)
  - `external/openclaw/` (from https://github.com/openclaw/openclaw)
- NVIDIA API key configured in `.env` files:
  - `docker/hermes/.env`
  - `docker/openclaw/.env`

## Quick Setup

```bash
# Make script executable
chmod +x setup_docker_agents.sh

# Run automated setup
./setup_docker_agents.sh
```

This script:
1. Verifies external repos exist
2. Builds Docker images from source
3. Starts containers
4. Tests health endpoints
5. Runs detailed agent tests

## Manual Build Steps

### Step 1: Build Hermes Image

The Hermes Dockerfile builds a production-grade Debian container with:
- Patched SQLite 3.53.4 (fixes WAL corruption bug)
- Node.js 26
- Python with AI provider SDKs
- s6-overlay process supervision

```bash
cd external/hermes-agent
docker build -t hermes:latest -f Dockerfile .
cd ../..
```

Expected build time: **5-10 minutes**

### Step 2: Build OpenClaw Image

The OpenClaw Dockerfile uses multi-stage build with:
- Bun package manager
- Workspace dependency extraction
- Minimal runtime image (node:24-bookworm-slim)
- Plugin system and optional extensions

```bash
cd external/openclaw
docker build -t openclaw:latest -f Dockerfile .
cd ../..
```

Expected build time: **10-15 minutes**

### Step 3: Start Containers

```bash
docker compose up -d
```

### Step 4: Verify Health

```bash
# Check health endpoints
curl http://localhost:8001/health    # Hermes
curl http://localhost:8002/health    # OpenClaw

# Or run the test script
python test_agents.py
```

## Docker Compose Configuration

File: `docker-compose.yml`

### Hermes Service

```yaml
hermes:
  build:
    context: ./external/hermes-agent
    dockerfile: Dockerfile
  command: ["gateway", "run"]
  ports:
    - "8001:8642"
  environment:
    API_SERVER_ENABLED: "true"
    API_SERVER_HOST: "0.0.0.0"
    API_SERVER_PORT: "8642"
```

- **Image**: Built from external/hermes-agent Dockerfile
- **Command**: `gateway run` — starts HTTP gateway
- **Port mapping**: 8001 (host) → 8642 (container)
- **Volume**: `docker/hermes/data:/opt/data` for persistent state

### OpenClaw Service

```yaml
openclaw:
  build:
    context: ./external/openclaw
    dockerfile: Dockerfile
  command: ["node", "openclaw.mjs", "gateway", "--bind", "0.0.0.0", "--port", "8002"]
  ports:
    - "8002:8002"
  environment:
    MODEL_NAME: "nvidia/nemotron-3-super-120b-a12b"
    MODEL_BASE_URL: "https://integrate.api.nvidia.com/v1"
```

- **Image**: Built from external/openclaw Dockerfile
- **Command**: `node openclaw.mjs gateway` — starts Node.js gateway
- **Port**: 8002
- **LLM Backend**: NVIDIA Nemotron (configured via .env)

## Environment Configuration

### Hermes (.env)

File: `docker/hermes/.env`

```env
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=<your-nvidia-api-key>
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=<auth-key>
```

### OpenClaw (.env)

File: `docker/openclaw/.env`

```env
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=<your-nvidia-api-key>
AGENT_API_KEY=<auth-key>
```

## Testing Agent Endpoints

### Health Check

```bash
curl http://localhost:8001/health
curl http://localhost:8002/health
```

### Chat Completion Request

```bash
# Hermes
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes",
    "messages": [{"role": "user", "content": "Hello, Hermes!"}],
    "max_tokens": 100
  }'

# OpenClaw
curl -X POST http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw",
    "messages": [{"role": "user", "content": "Hello, OpenClaw!"}],
    "max_tokens": 100
  }'
```

## Benchmark Configuration

Configure the benchmark runner to use Docker agents:

```bash
export BENCH_HERMES_ENDPOINT=http://localhost:8001
export BENCH_HERMES_API_KEY=any-value-works
export BENCH_HERMES_DEPLOYMENT_TYPE=local_docker

export BENCH_OPENCLAW_ENDPOINT=http://localhost:8002
export BENCH_OPENCLAW_API_KEY=any-value-works
export BENCH_OPENCLAW_DEPLOYMENT_TYPE=local_docker
```

Or add to `.env`:

```env
BENCH_HERMES_ENDPOINT=http://localhost:8001
BENCH_HERMES_API_KEY=any-value-works
BENCH_HERMES_DEPLOYMENT_TYPE=local_docker

BENCH_OPENCLAW_ENDPOINT=http://localhost:8002
BENCH_OPENCLAW_API_KEY=any-value-works
BENCH_OPENCLAW_DEPLOYMENT_TYPE=local_docker
```

## Running Benchmarks

```bash
# Single test
aab run "Explain quantum computing in one sentence"

# Check status
aab status

# View results after collecting data
aab report --days 1

# Evaluate responses
aab evaluate
```

## Troubleshooting

### Build Fails

**Problem**: Docker build hangs or fails

**Solutions**:
1. Increase Docker memory: Docker Desktop Settings → Resources → Memory: 6-8 GB
2. Check internet connection (downloads dependencies)
3. View build logs:
   ```bash
   docker compose build --progress=plain
   ```

### Container Won't Start

**Problem**: Container exits immediately

**Solutions**:
1. Check logs:
   ```bash
   docker compose logs hermes
   docker compose logs openclaw
   ```
2. Verify environment variables:
   ```bash
   docker compose exec hermes env | grep API_SERVER
   docker compose exec openclaw env | grep MODEL
   ```

### Health Check Fails

**Problem**: Curl returns connection refused or timeout

**Solutions**:
1. Wait longer (full startup takes 30-60 seconds):
   ```bash
   sleep 60
   curl http://localhost:8001/health
   ```
2. Check if ports are in use:
   ```bash
   lsof -i :8001
   lsof -i :8002
   ```
3. View container resource usage:
   ```bash
   docker stats
   ```

### NVIDIA API Errors

**Problem**: Container logs show "Failed to connect to NVIDIA API"

**Solutions**:
1. Verify API key in `.env`:
   ```bash
   docker compose exec hermes printenv MODEL_API_KEY
   ```
2. Test NVIDIA API directly:
   ```bash
   curl -X GET https://integrate.api.nvidia.com/v1/models \
     -H "Authorization: Bearer <your-api-key>"
   ```
3. Check network connectivity from container:
   ```bash
   docker compose exec hermes curl https://integrate.api.nvidia.com/v1/models
   ```

### Ports Already in Use

**Problem**: Port 8001 or 8002 already in use

**Solutions**:
1. Find what's using the port:
   ```bash
   lsof -i :8001
   ```
2. Use different ports in `docker-compose.yml`:
   ```yaml
   ports:
     - "9001:8642"  # Use 9001 instead of 8001
   ```
3. Update benchmark config:
   ```bash
   export BENCH_HERMES_ENDPOINT=http://localhost:9001
   ```

## Remote Deployment

For deployment on a remote VM or Azure Container Instances:

### 1. Build Images on Remote Host

```bash
# SSH to remote host
ssh user@remote-host

# Clone or transfer external repos
git clone https://github.com/nousresearch/hermes-agent.git external/hermes-agent
git clone https://github.com/openclaw/openclaw.git external/openclaw

# Build images
docker build -t hermes:latest -f external/hermes-agent/Dockerfile .
docker build -t openclaw:latest -f external/openclaw/Dockerfile .
```

### 2. Update Benchmark Config

```bash
export BENCH_HERMES_ENDPOINT=http://remote-host:8001
export BENCH_OPENCLAW_ENDPOINT=http://remote-host:8002
```

### 3. Start Containers on Remote

```bash
docker compose up -d
```

### 4. Run Benchmarks from Local

```bash
aab run "Your test prompt"
```

Requests will be sent from local machine to remote Docker containers via HTTP.

## What's Actually Running

### Hermes

- **Framework**: NousResearch Hermes Agent
- **Architecture**: Debian 13 + Node.js 26 + Python + SQLite
- **API**: OpenAI-compatible chat completions
- **Features**: Tool use, web search, code execution, multiple terminals

### OpenClaw

- **Framework**: OpenClaw AI Agent Gateway
- **Architecture**: Node.js 24 + Bun + TypeScript
- **API**: OpenAI-compatible chat completions
- **Features**: Tool use, code execution, browser automation, plugin system

### LLM Backend

Both agents use **NVIDIA Nemotron-3-Super-120B** as the underlying LLM, accessed via NVIDIA API.

## Key Files

- **docker-compose.yml** — Defines both services, ports, volumes, environment
- **setup_docker_agents.sh** — Automated setup script
- **docker/hermes/.env** — Hermes configuration (API keys, ports)
- **docker/openclaw/.env** — OpenClaw configuration (API keys, ports)
- **external/hermes-agent/** — Hermes source repository
- **external/openclaw/** — OpenClaw source repository
- **test_agents.py** — Health check and API test script

## Next Steps

1. **Build and start**: `./setup_docker_agents.sh`
2. **Verify health**: `python test_agents.py`
3. **Run benchmarks**: `aab run "Your prompt"`
4. **Collect data**: Run benchmarks daily with real tasks
5. **Generate report**: `aab report --days 7`

## Notes

- First build takes 15-20 minutes (dependencies compile)
- Startup takes 30-60 seconds (agents initialize)
- Agents require NVIDIA API access (internet connection needed)
- Both agents run independently; one failure doesn't affect the other
- Benchmark runner and agents are isolated (can run on different machines)
