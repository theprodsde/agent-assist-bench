# Docker Setup for AgentAssistBench

This directory contains Docker configurations to build and run Hermes and OpenClaw agents from source, configured for the AgentAssistBench evaluation framework.

## Architecture

Both agents are built from the official source repositories cloned in `external/`:
- **Hermes** (`external/hermes-agent`) → builds as Python app on Debian
- **OpenClaw** (`external/openclaw`) → builds as Node.js app 

Both expose OpenAI-compatible `/v1/chat/completions` endpoints backed by NVIDIA's free tier Nemotron 120B model.

## Prerequisites

1. **NVIDIA API Key** — Get one free at https://console.nvidia.com/nvcf/functions
   - Sign up for NVIDIA API Catalog
   - Create an API key for Nemotron-3-Super-120B

2. **Source repos cloned** in `external/`:
   ```bash
   cd external
   git clone https://github.com/nousresearch/hermes-agent.git hermes-agent
   git clone https://github.com/openclaw/openclaw.git openclaw
   ```

3. **Docker and Docker Compose** installed

## Setup

### 1. Configure environment variables

Each agent needs its NVIDIA API key. Create `.env` files:

**`docker/hermes/.env`:**
```env
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=nvapi-YOUR_ACTUAL_KEY_HERE
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_KEY=your-hermes-benchmark-key
```

**`docker/openclaw/.env`:**
```env
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=nvapi-YOUR_ACTUAL_KEY_HERE
AGENT_API_KEY=your-openclaw-benchmark-key
```

Or copy from examples:
```bash
cp docker/hermes/.env.example docker/hermes/.env
cp docker/openclaw/.env.example docker/openclaw/.env
# Then edit both files with your NVIDIA API key
```

### 2. Build and start

```bash
# Build both images (first time only, ~10 minutes each)
docker compose build

# Start both containers in background
docker compose up -d

# Check status
docker compose ps
# Should show both containers as "Up"

# View logs
docker compose logs -f hermes
docker compose logs -f openclaw
```

### 3. Verify health

```bash
# Check Hermes is ready
curl http://localhost:8001/health

# Check OpenClaw is ready
curl http://localhost:8002/health

# Both should return HTTP 200 with health status
```

### 4. Run benchmark

From the project root:

```bash
export BENCH_HERMES_ENDPOINT=http://localhost:8001
export BENCH_OPENCLAW_ENDPOINT=http://localhost:8002
source docker/hermes/.env docker/openclaw/.env

# Run a test benchmark
aab run "Explain the difference between microservices and monolithic architecture"

# Check status
aab status
```

## Troubleshooting

### "Connection refused" on health check

**Hermes not starting:**
```bash
docker logs hermes-bench
```
Check for Python import errors or missing dependencies.

**OpenClaw not starting:**
```bash
docker logs openclaw-bench
```
Check for Node.js module errors.

### "NVIDIA API key invalid"

- Verify the key format: should start with `nvapi-`
- Test directly: 
  ```bash
  curl -H "Authorization: Bearer $MODEL_API_KEY" \
    https://integrate.api.nvidia.com/v1/chat/completions \
    -X POST \
    -d '{"messages":[{"role":"user","content":"hi"}],"model":"nvidia/nemotron-3-super-120b-a12b"}'
  ```
- Check key hasn't expired on https://console.nvidia.com/nvcf/functions

### "Setup requires explicit risk acknowledgement"

This is normal for OpenClaw. The docker-compose startup script handles it with `--accept-risk` flag. Wait for container to stabilize (~30s).

### Out of memory during build

If building on low-memory machine:
```bash
docker compose build --no-cache --memory 2g
```

## Development

### Rebuild after code changes

If you modify `external/hermes-agent` or `external/openclaw`:

```bash
# Rebuild without cache
docker compose build --no-cache

# Restart containers
docker compose restart
```

### Run with custom config

Place a custom `config.yaml` in `docker/hermes/` or `docker/openclaw/` — it's mounted as read-only and will override defaults.

### Stop and clean up

```bash
# Stop containers
docker compose stop

# Remove containers (data persists in volumes)
docker compose down

# Remove containers AND data
docker compose down -v
```

## Architecture notes

- **Hermes**: Runs `python3 -m hermes.server` exposing port 8642 internally, mapped to 8001 externally
- **OpenClaw**: Runs `node openclaw.mjs gateway` on port 8002 with `--bind lan` for network access
- **Volumes**: Both have persistent data volumes so agent state survives container restarts
- **Environment**: Both read `.env` files for API keys and configuration
- **Health checks**: Docker monitors both containers and restarts on failure (`restart: unless-stopped`)

## Next Steps

1. Run benchmarks for 1 week collecting real task data
2. Generate reports: `aab report --days 7`
3. Deploy to ACA or VM with same docker-compose configuration
