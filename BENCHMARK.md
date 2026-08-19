# AgentAssistBench — Live Benchmark Record

This file tracks the current benchmark configuration, verified capabilities, known
limitations, and methodology decisions. Update it whenever the setup changes.

---

## ⚠️ Benchmark Validity Notice

All results recorded in this file before the **"Account split" change** were collected
with both agents sharing the same NVIDIA API key. A shared key means NVIDIA's
server-side KV cache can carry state between requests, unfairly benefiting whichever
agent runs second. These results are labelled `[shared-key — invalid for latency comparison]`.

**Valid benchmarks start after both .env files are updated with separate account keys
and both containers are restarted.**

---

## Setup State (last verified: 2026-08-15)

### Containers

| Container | Image | Port | Status |
|---|---|---|---|
| `hermes-agent` | Built from `external/hermes-agent` | `8001` → container `8642` | Running, healthy |
| `openclaw-agent` | `ghcr.io/openclaw/openclaw:latest` | `8002` → container `8002` | Running, healthy |

### LLM Backend — both agents use the same model

| Setting | Value |
|---|---|
| Model | `nvidia/nemotron-3-super-120b-a12b` |
| Provider | NVIDIA Integrate API |
| Endpoint | `https://integrate.api.nvidia.com/v1` |
| API key isolation | ⚠️ **Currently same key in both .env files** — update to separate NVIDIA accounts before comparing latency |

### Tool Capabilities (verified working)

| Tool | Hermes | OpenClaw |
|---|---|---|
| **web_search** | ✅ `ddgs` package (DuckDuckGo, no key needed) | ✅ DuckDuckGo plugin (`plugins enable duckduckgo`) |
| **web_fetch / web_extract** | ✅ direct URL fetch | ✅ `web_fetch` + `dir_fetch` tools |
| **terminal / exec** | ✅ `HERMES_YOLO_MODE=1` (no approval prompts) | ✅ `exec` tool (ask=off mode) |
| **browser** | ✅ Playwright baked into image | ✅ browser extension loaded |
| **file read/write** | ✅ | ✅ |
| **memory** | ✅ persistent across sessions | ✅ via `memory-core` plugin |

### How Web Search Was Enabled (no API keys)

**Hermes:** `ddgs` (DuckDuckGo Python client) installed into the data volume's
lazy-packages directory, which Hermes adds to `sys.path` at bootstrap.

```bash
docker exec -u root hermes-agent /usr/local/bin/uv pip install ddgs \
  --target /opt/data/lazy-packages \
  --python /opt/hermes/.venv/bin/python3
```

Re-run this if the data volume is reset (e.g. after `docker compose down -v`).

**OpenClaw:** DuckDuckGo plugin enabled via the CLI, persisted in `docker/openclaw/state/openclaw.json`:

```bash
docker exec openclaw-agent node openclaw.mjs plugins enable duckduckgo
docker compose restart openclaw
```

The config is already committed in `docker/openclaw/state/openclaw.json` so this only
needs repeating if the state directory is wiped.

---

## Benchmark Methodology

### Why sequential execution

`BENCH_DELAY_SECONDS=2.0` — agents run one after the other with a 2-second gap.
This prevents 429 errors when both agents share a single NVIDIA API key. With two
separate NVIDIA accounts (one per agent), 429s are still possible under heavy load;
the delay adds a safety margin and ensures latency measurements are independent.

### Cost comparison

`BENCH_HERMES_COST_PER_HOUR` and `BENCH_OPENCLAW_COST_PER_HOUR` measure **active
compute time** per request:

```
cost_per_request = (latency_ms / 3_600_000) × cost_per_hour
```

**Accurate for:** relative comparison — a Hermes 3s request costs N× less compute
than an OpenClaw 11s request at the same hourly rate.

**Not captured:** idle container cost (min_replicas=1 runs 24/7). For Azure ACA
consumption at 2 vCPU / 4 GB, reference pricing is ~$0.22/hr per container.
Set both cost vars to `0.22` for relative cost comparison.

**Token costs:** API is free (NVIDIA credits). Hermes exposes full token counts
(`prompt_tokens`, `completion_tokens`) in the response. OpenClaw returns `0` for
all token fields — it processes tokens internally across multiple NVIDIA calls but
doesn't surface them in the `/v1/chat/completions` response.

### Fairness constraints

For comparable results, every benchmark run should:

1. Send the **same prompt** to both agents
2. Use a prompt that requires the **same capabilities** (both have search, exec, file tools)
3. Avoid prompts that only one agent handles well by design (e.g. very long multi-step
   agentic tasks where Hermes has a 16k token system prompt overhead advantage for
   simple queries but a disadvantage for long chains)

---

## Known Limitations

### OpenClaw token gap
`prompt_tokens`, `completion_tokens`, and `estimated_cost_usd` are always `null`
in the `executions` table for OpenClaw. The report's `Avg Cost` column will show
only Hermes data. Use latency as the primary cost proxy.

### Hermes system prompt overhead
Hermes injects ~16,300 tokens of system prompt + tool schemas on every request.
For a 10-word factual question, this makes Hermes appear to "consume" far more
tokens than OpenClaw. This overhead is real (it costs time and NVIDIA quota) but
it also means Hermes has richer context for tool selection and agentic reasoning.

### DuckDuckGo search quality variation
Both agents use DuckDuckGo but through different clients (`ddgs` Python package vs
the OpenClaw DDG plugin). Results can vary between requests due to DuckDuckGo's
anti-scraping measures. Neither implementation has authentication so rate-limits
or CAPTCHA blocks are possible under heavy benchmarking.

### OpenClaw web_search plugin stability
The `duckduckgo` plugin has `activation.onStartup: false` in its manifest. It loads
correctly after `openclaw plugins enable duckduckgo` + restart but may revert if
OpenClaw updates or the state volume is reset. Re-run the enable command if
`web_search` starts returning "disabled" errors in the OpenClaw log.

### Hermes ddgs persistence
`ddgs` is installed in `docker/hermes/data/lazy-packages/` — the mounted data volume.
If the data volume is deleted, it must be reinstalled. It does NOT survive
`docker compose down -v`.

### Hermes web dashboard (port 8080)
Configured in `docker-compose.yml` (`HERMES_DASHBOARD=true`) but the dashboard
port is a separate service inside the container. Availability depends on the
Hermes version — check `http://localhost:8080` after `docker compose up`. If it's
not accessible, the API server on port 8001 still works for benchmarking.

---

## How Agent Docker Images Are Built

This section documents exactly what was done to containerise Hermes and OpenClaw.
Follow the same pattern when adding a third agent.

### The Contract — what every agent container must expose

The benchmark runner calls exactly three endpoints. Any agent framework that exposes
these can be added to the benchmark without writing a custom Python adapter:

| Endpoint | Purpose | Expected response |
|---|---|---|
| `GET /health` | Liveness check | Any `2xx` with any body |
| `GET /v1/models` | Health check used by adapter | Any `2xx` (body can be empty list) |
| `POST /v1/chat/completions` | Agent execution | OpenAI chat completions JSON |

Authentication is `Authorization: Bearer <token>` on every request.
The `v1/` prefix is required — the benchmark endpoint config includes it
(e.g. `BENCH_HERMES_ENDPOINT=http://host:port/v1`).

---

### Agent 1 — Hermes

**Source:** `external/hermes-agent/` (full Python/Node monorepo, cloned from upstream)

**Approach:** Built from source using the upstream `Dockerfile`. The image is large
(~4 GB) because it includes Python 3.13, Node 26, SQLite compiled from source,
Playwright/Chromium for browser tools, and all Python/npm dependencies.

**Why source build instead of published image:**  
The upstream `nousresearch/hermes-agent` published image was not reliably available.
Building from the cloned source gave a reproducible, offline-buildable image.

**Key decisions made during setup:**

1. **Enable the API server** — Hermes is primarily a messaging/gateway platform.
   Its OpenAI-compatible HTTP API is opt-in, not on by default. Required env vars:
   ```
   API_SERVER_ENABLED=true
   API_SERVER_HOST=0.0.0.0
   API_SERVER_PORT=8642
   API_SERVER_KEY=<bearer-token>
   ```

2. **Configure the model** — Hermes reads model/provider from a mounted `config.yaml`.
   The critical fields (set in `docker/hermes/data/config.yaml`, mounted at `/opt/data/config.yaml`):
   ```yaml
   model:
     default: "nvidia/nemotron-3-super-120b-a12b"
     provider: "nvidia"   # reads NVIDIA_API_KEY env var
   ```
   Using `provider: "nvidia"` (not `"custom"` or `"auto"`) is essential — `"auto"`
   would route to OpenRouter when `OPENAI_API_KEY` is present.

3. **Fix config version** — The config must include `_config_version: 12` (or higher)
   or Hermes logs a migration warning and may ignore some settings. Hermes
   auto-migrates the file to the current version on first start; it will rewrite
   `config.yaml` to its internal format.

4. **Auto-approve tool calls** — By default Hermes asks the user for permission
   before running terminal commands or code. In a headless benchmark there is no
   user, so the approval would block forever. Setting `HERMES_YOLO_MODE=1` bypasses
   all approval gates. Appropriate for a controlled benchmark environment, not production.

5. **Web search without API key** — Hermes's `web_search` tool auto-selects the
   `ddgs` Python package (DuckDuckGo, free) when it's importable. The package is
   NOT in the published image. Install it into the data volume after first start:
   ```bash
   docker exec -u root hermes-agent /usr/local/bin/uv pip install ddgs \
     --target /opt/data/lazy-packages \
     --python /opt/hermes/.venv/bin/python3
   ```
   Hermes's bootstrap adds `/opt/data/lazy-packages` to `sys.path` on every start,
   so the package survives container restarts. It does NOT survive `docker compose down -v`.

6. **Healthcheck port** — Hermes binds its API server at container port `8642`, not
   at the host-mapped port (`8001`). The healthcheck must use the container port:
   ```yaml
   healthcheck:
     test: ["CMD", "curl", "-fsS", "http://localhost:8642/health"]
   ```

**Files created:**
- `docker/hermes/.env` — API keys and runtime config
- `docker/hermes/data/config.yaml` — model/provider config (Hermes rewrites this on start)
- `docker/hermes/data/lazy-packages/` — ddgs and its dependencies (post-install)
- Entry in `docker-compose.yml` under `hermes:`

---

### Agent 2 — OpenClaw

**Source:** `ghcr.io/openclaw/openclaw:latest` (official pre-built image)

**Approach:** A thin wrapper Dockerfile (`docker/openclaw/Dockerfile.source`) pulls
the official published image and overrides the default `CMD`. Building from source
(`external/openclaw/`) was attempted but failed consistently — the pnpm install step
timed out downloading large npm packages (`playwright-core`, `@openai/codex`, etc.)
over a slow connection. The pre-built image is the practical choice.

**Why the official image includes the NVIDIA extension:**  
The nvidia extension has `"enabledByDefault": true` in its manifest and is compiled
into the published image. Setting `NVIDIA_API_KEY` auto-activates it at runtime.

**Key decisions made during setup:**

1. **Bind to `lan` (0.0.0.0)** — OpenClaw's gateway defaults to loopback (`127.0.0.1`)
   for security. Docker bridge networking requires binding to all interfaces to be
   reachable from the host. Pass `--bind lan` in the container command:
   ```yaml
   command: ["node", "openclaw.mjs", "gateway", "--bind", "lan", "--port", "8002"]
   ```

2. **Pre-configure `openclaw.json`** — OpenClaw stores all config in a SQLite DB +
   a JSON file under `~/.openclaw/`. Without config the gateway refuses to start
   (`missing gateway.mode`). The pre-config at `docker/openclaw/state/openclaw.json`
   (mounted as `/home/node/.openclaw`) sets the minimum required fields:
   ```json
   {
     "gateway": {
       "mode": "local",
       "auth": { "token": { "source": "env", "provider": "default", "id": "OPENCLAW_GATEWAY_TOKEN" } },
       "http": { "endpoints": { "chatCompletions": { "enabled": true } } }
     },
     "agents": {
       "defaults": { "model": { "primary": "nvidia/nemotron-3-super-120b-a12b" } }
     }
   }
   ```
   Three fields were non-obvious to discover:
   - `gateway.mode: "local"` — required; gateway won't start without it
   - `chatCompletions.enabled: true` — the `/v1/chat/completions` endpoint is **off by default**
   - The `token` as a SecretRef (`{"source":"env",...}`) — plain string also works

3. **Enable DuckDuckGo web search** — The DDG plugin ships in the image but has
   `activation.onStartup: false`, so it doesn't register as a search provider
   until explicitly enabled. Run once after first start:
   ```bash
   docker exec openclaw-agent node openclaw.mjs plugins enable duckduckgo
   docker compose restart openclaw
   ```
   This writes `plugins.entries.duckduckgo.enabled: true` to `openclaw.json` in the
   mounted state directory, so the setting persists across restarts.

4. **Gateway auth token** — OpenClaw uses `OPENCLAW_GATEWAY_TOKEN` (not `API_KEY`
   or `BEARER_TOKEN`). Set it to match `BENCH_OPENCLAW_API_KEY` in the benchmark's
   root `.env`. The SecretRef in `openclaw.json` reads it from the env var at runtime.

5. **Token counts are always zero** — OpenClaw's `/v1/chat/completions` response
   returns `{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}`. This is
   not a bug — OpenClaw runs multiple NVIDIA calls per agent turn internally and
   doesn't surface the aggregate token count in the HTTP response. Use latency as
   the cost proxy for OpenClaw.

**Files created:**
- `docker/openclaw/Dockerfile.source` — thin wrapper around official image
- `docker/openclaw/.env` — NVIDIA key and gateway auth token
- `docker/openclaw/state/openclaw.json` — pre-config (gateway mode, chatCompletions, model)
- Entry in `docker-compose.yml` under `openclaw:`

---

### Adding a Third Agent — Template

Follow these steps for any new agent framework:

**Step 1 — Identify the image**

Prefer the framework's official published Docker image. Only build from source if
the image doesn't exist or is broken. Building from source is expensive (10-45 min)
and fragile (network timeouts on large dependency trees).

**Step 2 — Create the directory structure**

```
docker/<agent-name>/
├── .env              # API keys and runtime config (gitignored if keys inside)
├── .env.example      # Safe template with placeholder values
├── Dockerfile        # or Dockerfile.source if wrapping a published image
└── state/            # Persistent volume mount (config, SQLite, etc.)
```

**Step 3 — Wire the HTTP contract**

The agent must serve at `/v1/chat/completions` with:
```http
POST /v1/chat/completions
Authorization: Bearer <token>
Content-Type: application/json

{"model": "<model-id>", "messages": [{"role": "user", "content": "..."}]}
```

The response must include `choices[0].message.content`. Token fields may be zero.

Common things to check:
- Default bind address — most frameworks default to `127.0.0.1`; override to `0.0.0.0`
- Auth — find the env var that sets the bearer token (not always called `API_KEY`)
- Model config — LLM provider/key is usually a separate env var from the framework auth
- Chat completions toggle — some frameworks disable this endpoint by default (like OpenClaw)

**Step 4 — Add to `docker-compose.yml`**

```yaml
  <agent-name>:
    build:
      context: ./docker/<agent-name>        # or ./external/<agent-name> for source build
      dockerfile: Dockerfile.source
    container_name: <agent-name>-agent
    restart: unless-stopped
    command: [...]                           # override if default doesn't bind to 0.0.0.0
    ports:
      - "<host-port>:<container-port>"
    volumes:
      - ./docker/<agent-name>/state:/home/...  # wherever the framework stores config
    env_file:
      - docker/<agent-name>/.env
    environment:
      <FRAMEWORK_LLM_KEY>: "..."
      <FRAMEWORK_BIND_HOST>: "0.0.0.0"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:<container-port>/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 90s
```

**Step 5 — Add to `benchmark/cli/wiring.py`**

For a framework that speaks the OpenAI chat completions format (most do), no new
Python adapter is needed — use `OpenAICompatibleAdapter` directly:

```python
from benchmark.config.settings import Settings  # add new settings fields
from benchmark.agents.openai_compatible import OpenAICompatibleAdapter

# In create_context():
newagent_key = settings.newagent_api_key.get_secret_value()
if newagent_key:
    adapter = OpenAICompatibleAdapter(
        endpoint=settings.newagent_endpoint,
        model="<model-id-that-the-gateway-accepts>",
        agent_name="<agent-name>",
        agent_version="1.0.0",
        api_key=newagent_key,
    )
    registry.register(adapter, _resolve_deployment_type(settings.newagent_deployment_type),
                      settings.newagent_endpoint)
    execution_order.append(("<agent-name>", ...))
```

Add the corresponding settings to `benchmark/config/settings.py`:
```python
newagent_endpoint: str = "http://localhost:<port>/v1"
newagent_api_key: SecretStr = SecretStr("")
newagent_deployment_type: str = "local_docker"
newagent_cost_per_hour: float | None = None
```

And to the root `.env`:
```env
BENCH_NEWAGENT_ENDPOINT=http://localhost:<port>/v1
BENCH_NEWAGENT_API_KEY=<bearer-token>
BENCH_NEWAGENT_COST_PER_HOUR=0.22
```

**Step 6 — Enable free web search (if the framework supports it)**

Check if the framework has a built-in search tool. If it needs an external package,
install it into a data-volume directory using the framework's package manager. If it
has a plugin system, enable the DuckDuckGo or similar free plugin. Document the
steps in this file under a new "Agent N" section, following the Hermes and OpenClaw
examples above.

**Step 7 — Document in this file**

Add a new `### Agent N — <FrameworkName>` section covering:
- Image source (official or source build, and why)
- Non-obvious configuration decisions
- How web search was enabled
- Files created
- Any known limitations for benchmarking

---

## Category Tags

Use `--tag` on every `aab run` to get useful per-category reports. Recommended tags:

| Tag | Description | Good test for |
|---|---|---|
| `coding` | Code generation, debugging, refactoring | Tool use (exec, file), code quality |
| `research` | Information lookup, summaries | web_search, web_extract accuracy |
| `devops` | CLI, Docker, infra, monitoring | Terminal tool, technical accuracy |
| `writing` | Docs, emails, articles | Reasoning quality, verbosity |
| `browser` | UI testing, web automation | Browser tool, multi-step |

Report becomes meaningful at 5+ runs per category per agent.

---

## Quick Reference — Restart Commands

```bash
# Full restart
docker compose up -d

# Hermes only (config change in docker/hermes/data/config.yaml)
docker compose restart hermes

# OpenClaw only (config change in docker/openclaw/state/openclaw.json)
docker compose restart openclaw

# Re-install ddgs after data volume reset
docker exec -u root hermes-agent /usr/local/bin/uv pip install ddgs \
  --target /opt/data/lazy-packages --python /opt/hermes/.venv/bin/python3

# Re-enable DuckDuckGo search in OpenClaw after state reset
docker exec openclaw-agent node openclaw.mjs plugins enable duckduckgo
docker compose restart openclaw

# Verify search works (both agents)
curl -s -H "Authorization: Bearer <HERMES_API_KEY>" \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"web_search: test"}]}' \
  -H "Content-Type: application/json" http://localhost:8001/v1/chat/completions
```

---

## Benchmark Run — With Search (2026-08-15)

First fair comparison with both agents having web search enabled.

| Metric | Hermes | OpenClaw |
|---|---|---|
| Search backend | `ddgs` (DuckDuckGo Python) | DuckDuckGo plugin |
| Search test query | "hermes agent framework github" | "hermes agent framework github" |
| Search working | ✅ | ✅ |
| Prompt tokens (search query) | 90,550 (includes search results) | 0 (not reported) |
| Key limitation | 90k+ token overhead per search | Token counts opaque |

Both agents returned real URLs from DuckDuckGo for the same query. Results differed
slightly due to DuckDuckGo ranking variation between requests.

### Research benchmark: "What is Hermes agent framework by NousResearch" [shared-key — invalid for latency comparison]

| | Hermes | OpenClaw |
|---|---|---|
| Latency | **40.4s** | **30.3s** |
| Prompt tokens | 104,431 (search results in context) | 0 (not reported) |
| Completion tokens | 1,063 | 0 (not reported) |
| Search used | ✅ Yes (103k tokens = search results fetched) | ✅ Yes (DuckDuckGo DDG plugin) |
| Response quality | Detailed, mentioned VPS/GPU/Modal/Telegram | Accurate, cited NousResearch URL |

**Observation:** OpenClaw was faster (30s vs 40s) on this research task. Hermes's
104k prompt tokens indicate it fetched and loaded substantially more web content
into context. Both answers were accurate and web-grounded.
