# Docker Agent Setup — Real Frameworks

## The Correct Architecture

Both agent frameworks expose HTTP gateways with OpenAI-compatible `/v1/chat/completions` endpoints:

```
Benchmark Runner (localhost)
    ↓ (HTTP requests)
┌─────────────────────┐
│ Hermes Gateway      │ (port 8001)
│ (Real agent)        │
└─────────────────────┘

┌─────────────────────┐
│ OpenClaw Gateway    │ (port 8002)
│ (Real agent)        │
└─────────────────────┘
```

## Hermes Setup

**Image**: `nousresearch/hermes-agent:latest`
**Command**: `gateway run`
**Port**: 8001 (mapped from 8642 inside container)
**API Endpoint**: `http://localhost:8001/v1/chat/completions`

### How Hermes Gateway Works

- Starts an HTTP gateway that accepts chat requests
- Exposes OpenAI-compatible API
- Routes requests to the agent backend
- Configured via environment variables in `docker/hermes/.env`

### Required Environment Variables

```env
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=<your-nvidia-api-key>
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=<auth-key>
```

## OpenClaw Setup

**Image**: `openclaw:latest` (from official OpenClaw repository)
**Command**: `node dist/index.js gateway --bind 0.0.0.0 --port 8002`
**Port**: 8002
**API Endpoint**: `http://localhost:8002/v1/chat/completions`

### How OpenClaw Gateway Works

- Starts a Node.js gateway that accepts chat requests
- Exposes OpenAI-compatible API
- Routes requests to the agent backend
- Handles tool execution, code runs, browser automation

### Required Environment Variables

```env
MODEL_NAME=nvidia/nemotron-3-super-120b-a12b
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=<your-nvidia-api-key>
```

## Startup

### 1. Pull Images

```bash
docker pull nousresearch/hermes-agent:latest
docker pull openclaw:latest  # From https://github.com/openclaw/openclaw
```

### 2. Start Containers

```bash
docker compose up -d
```

### 3. Verify Health

```bash
curl http://localhost:8001/health    # Hermes
curl http://localhost:8002/health    # OpenClaw
```

Or use the test script:

```bash
python test_agents.py
```

## Testing Endpoints

### Hermes Chat Request

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hermes",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

### OpenClaw Chat Request

```bash
curl -X POST http://localhost:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

## Configuring Benchmark Runner

Set environment variables:

```env
BENCH_HERMES_ENDPOINT=http://localhost:8001
BENCH_HERMES_API_KEY=any-value-works
BENCH_HERMES_DEPLOYMENT_TYPE=local_docker

BENCH_OPENCLAW_ENDPOINT=http://localhost:8002
BENCH_OPENCLAW_API_KEY=any-value-works
BENCH_OPENCLAW_DEPLOYMENT_TYPE=local_docker
```

Or in `.env` file in project root.

## Running Benchmarks

```bash
# Single benchmark
aab run "Explain quantum computing in one sentence"

# Check status
aab status

# View results
aab report --days 1
```

## Remote Deployment (VM/ACA)

For deployment on a remote VM or Azure Container Instances:

1. Update endpoints in environment:
   ```env
   BENCH_HERMES_ENDPOINT=http://vm-ip:8001
   BENCH_OPENCLAW_ENDPOINT=http://vm-ip:8002
   ```

2. Start containers on remote host:
   ```bash
   docker-compose up -d
   ```

3. Run benchmarks from local machine — they send HTTP requests to remote endpoints

## Troubleshooting

### Container won't start

```bash
docker compose logs hermes
docker compose logs openclaw
```

### Health check failing

- Wait 30+ seconds for containers to initialize
- Check network connectivity: `telnet localhost 8001`
- Verify NVIDIA API key in `.env` files

### API requests timeout

- Check container logs: `docker compose logs`
- Verify NVIDIA API is accessible from container
- Check firewall rules

### Port conflicts

If ports 8001/8002 are in use:

Edit `docker-compose.yml` to use different ports, then update `BENCH_HERMES_ENDPOINT` and `BENCH_OPENCLAW_ENDPOINT`.
