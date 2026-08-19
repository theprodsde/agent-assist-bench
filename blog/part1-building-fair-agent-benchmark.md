# How I Built a Benchmark That Actually Tests AI Agent Frameworks — Not Just Their LLMs

## Part 1: The Setup — Getting Hermes and OpenClaw to Compete Fairly on the Same Hardware

---

There is a question I kept asking myself every time I evaluated an AI assistant for
daily work: **am I testing the framework, or just the model underneath it?**

Every published benchmark — GAIA, SWE-bench, WebArena — gives you a score for the
model. But when you choose an AI assistant for daily use, you are not choosing a
model. You are choosing a complete stack: the framework that decides when to call
tools, the memory system that remembers context across sessions, the web search
capability that can look up something you do not know, and the infrastructure that
determines whether a request takes 2 seconds or 40.

That question led me to build **AgentAssistBench** — an open-source CLI framework
that benchmarks the complete agent stack on your actual work, not curated test cases.
This is Part 1: how I got two real agent frameworks running, pointing at the same
LLM, and competing fairly.

---

## Why This Benchmark Is Different

Most agent benchmarks make a subtle error: they test a *model* running agentic tasks.
That is not what you deploy. You deploy Hermes, or OpenClaw, or AutoGen — a full
framework with its own system prompt, tool routing logic, and memory architecture.
Two frameworks running the same model on the same prompt can produce wildly different
outputs, at wildly different latencies, for wildly different costs.

AgentAssistBench is built around a different philosophy:

- **Same LLM, different frameworks** — both agents use NVIDIA Nemotron-3-Super-120B
  via the same API endpoint, so the underlying model quality is controlled
- **Your real tasks, not curated ones** — you submit the prompts you actually care about,
  tagged by category (coding, research, devops, writing)
- **Human evaluation, not LLM-as-judge** — you rate responses 1-5 and pick your preferred
  agent; no automated scoring introduces its own bias
- **Infrastructure cost in the report** — latency × cost-per-hour gives you the real
  compute cost per request, not just model API cost

After 30 days of daily benchmarking the report looks like this:

```
Category    | Best Agent  | Win Rate | Avg Latency | Avg Cost/req
------------|-------------|----------|-------------|-------------
Coding      | Hermes      | 72%      | 3.4s        | $0.0003
Research    | OpenClaw    | 68%      | 11.2s       | $0.0009
DevOps      | Hermes      | 85%      | 5.1s        | $0.0004
```

That is the data I am collecting. This post covers how I built the setup to collect it
fairly.

---

## The Two Contenders

**Hermes** (by NousResearch) is a Python + Node agent that runs as a persistent gateway
process. It has a rich tool ecosystem built-in — web search, browser automation via
Playwright, terminal execution, persistent memory, cron scheduling — and exposes an
OpenAI-compatible HTTP API alongside its native Telegram/Discord interfaces. The Docker
image is about 4 GB because it bakes in Playwright/Chromium, a custom SQLite build, and
the full Python 3.13 + Node 26 stack.

**OpenClaw** is a TypeScript agent built on Node 24. It takes a modular plugin approach:
a small core with extensions for each capability — browser, search, file transfer, memory.
The gateway also exposes `/v1/chat/completions` but with security-first defaults — web
search is disabled unless you enable a provider, and the gateway binds to loopback unless
you explicitly override it.

Both are real agent frameworks, not thin wrappers. Both call their own tools. Both inject
their own system prompts. This is the thing being measured.

---

## The Setup: Two Containers, One Fair Race

The goal was simple: two containers, each calling NVIDIA independently, both reachable
by the benchmark CLI at `/v1/chat/completions`. Clean goal. Non-trivial execution.

### Architecture

```
Your Machine
    │
    ├── aab CLI
    │     └── runs aab run --tag coding "Write binary search in Python"
    │
    ├── hermes-agent  (port 8001 → container 8642)
    │     ├── NVIDIA Account A key  ← separate account, no shared KV cache
    │     └── ddgs (DuckDuckGo, free, no key needed) for web search
    │
    └── openclaw-agent  (port 8002)
          ├── NVIDIA Account B key  ← separate account, no shared KV cache
          └── DuckDuckGo plugin (built-in, free, no key needed) for web search
```

Both agents use separate NVIDIA accounts intentionally. A shared API key means the
server-side KV cache could benefit whichever agent runs second, biasing latency
measurements. Different accounts, different cache namespaces, clean comparison.

---

## Building Hermes

Hermes builds from source using the upstream `Dockerfile` in the cloned repository.
The build is thorough — it compiles SQLite from source to fix a WAL corruption bug in
Debian 13, copies Node 26 from the official image, installs Python dependencies via uv,
and bakes in Playwright.

**Non-obvious thing 1: the API server is opt-in.**

Hermes is primarily a messaging/gateway platform. Its OpenAI-compatible HTTP API is
off by default. You have to enable it:

```bash
# docker/hermes/.env
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=your-bearer-token
```

**Non-obvious thing 2: `provider: "auto"` routes to the wrong place.**

With `OPENAI_API_KEY` set, Hermes's auto-detect logic routes to OpenRouter, not to NVIDIA.
The model config in `docker/hermes/data/config.yaml` must be explicit:

```yaml
model:
  default: "nvidia/nemotron-3-super-120b-a12b"
  provider: "nvidia"   # reads NVIDIA_API_KEY — do NOT use "auto" here
```

**Non-obvious thing 3: tool approval blocks headless execution.**

Hermes asks for permission before running terminal commands. In a headless benchmark,
that approval prompt blocks forever. `HERMES_YOLO_MODE=1` bypasses all approval gates.
Fine for a controlled benchmark, not for production.

**Non-obvious thing 4: the healthcheck uses the container port, not the host port.**

Hermes binds at container port `8642`, mapped to host port `8001`. The Docker Compose
healthcheck runs inside the container, so it must use `8642`:

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "http://localhost:8642/health"]
```

---

## Building OpenClaw

The OpenClaw source build failed repeatedly. The `pnpm install` step downloads large
packages (`playwright-core`, `@openai/codex`, native binaries) and pnpm's internal
download timeout fires before they complete on a slow connection. After two failed
10-minute builds, I switched to the official pre-built image — a two-line Dockerfile:

```dockerfile
FROM ghcr.io/openclaw/openclaw:latest
CMD ["node", "openclaw.mjs", "gateway", "--bind", "lan"]
```

**Non-obvious thing 1: OpenClaw refuses to start without a config file.**

By design, OpenClaw will not boot with an empty state directory — it does not want to
expose an unconfigured gateway. I created `docker/openclaw/state/openclaw.json` and
mounted it at `/home/node/.openclaw`. The minimum required fields:

```json
{
  "gateway": {
    "mode": "local",
    "auth": {
      "token": { "source": "env", "provider": "default", "id": "OPENCLAW_GATEWAY_TOKEN" }
    },
    "http": {
      "endpoints": { "chatCompletions": { "enabled": true } }
    }
  },
  "agents": {
    "defaults": {
      "model": { "primary": "nvidia/nemotron-3-super-120b-a12b" }
    }
  }
}
```

Three things in that JSON that are easy to miss:
1. `gateway.mode: "local"` — required field, no default, gateway crashes without it
2. `chatCompletions.enabled: true` — the `/v1/chat/completions` endpoint is **off by default**
3. `auth.token` as a SecretRef object — reads the bearer token from an environment variable
   at runtime instead of hardcoding it in the file

---

## Web Search Without a Search API Key

This deserves its own section because it is the part that took the most effort and has
the most interesting outcome.

### The problem

Both agents have a `web_search` tool. Both failed to use it out of the box.

**Hermes** fell back to `firecrawl` as its default search backend — which also needs an
API key. Without any key, `web_search` returned an error. The agent answered from memory
instead, silently. No error in the benchmark, just wrong-category latency data (2s for
a knowledge answer vs 40s for a real web search).

**OpenClaw** reported "web_search is disabled or no provider is available" in its internal
log. The DuckDuckGo plugin ships with the image but has `activation.onStartup: false` in
its manifest, so it does not register as a search provider at startup.

### The fix: tool-based search with no search API key

Both agents were fixed using free, no-key-required approaches:

**Hermes — `ddgs` Python package**

`ddgs` is a Python client for DuckDuckGo's HTML search endpoint. It requires no API key,
no account, no configuration. Hermes's `web_search` tool auto-selects it when it is
importable. The package is not included in the image, but Hermes has a mechanism for
installing packages into the mounted data volume at runtime:

```bash
docker exec -u root hermes-agent /usr/local/bin/uv pip install ddgs \
  --target /opt/data/lazy-packages \
  --python /opt/hermes/.venv/bin/python3
```

Hermes's bootstrap script adds `/opt/data/lazy-packages` to `sys.path` on every start,
so the package is available from the next restart. The data volume is a bind-mounted
host directory, so it persists across container restarts — it only disappears if you
delete the volume entirely.

**OpenClaw — DuckDuckGo plugin**

The DuckDuckGo extension is already compiled into the OpenClaw image. It uses
DuckDuckGo's search directly, with no API key. One command enables it:

```bash
docker exec openclaw-agent node openclaw.mjs plugins enable duckduckgo
docker compose restart openclaw
```

That command writes `plugins.entries.duckduckgo.enabled: true` to `openclaw.json` in
the mounted state directory, so the setting persists across restarts.

### How the tool-calling works

This is worth explaining clearly, because "web search through tool calling" sounds more
complicated than it is.

When you send a request to `/v1/chat/completions`, neither agent forwards it directly to
NVIDIA. Instead:

1. The agent framework builds a request to NVIDIA that includes the user's prompt **plus**
   a list of available tools (web_search, exec, browser, etc.) in the model's context
2. NVIDIA Nemotron responds with either a text answer or a **tool call** — a JSON object
   saying "run web_search with query: ..."
3. The agent framework executes the tool call locally (DuckDuckGo in this case, running
   inside the container with no external API key)
4. The search results are injected back into the context
5. NVIDIA is called again with the original prompt + the search results
6. The final text response is returned to the benchmark caller

The entire search flow happens inside the container. The only outbound calls are:
- NVIDIA's API (for the LLM inference)
- DuckDuckGo's HTML endpoint (for the search results, no authentication)

No search API key. No Brave. No Exa. No Firecrawl. Just the LLM deciding to search,
the container doing the search locally, and the result fed back into the context.

### Proof it worked

Asking both agents to search for "hermes agent framework github":

**Hermes response:**
```
Top 3 results for "hermes agent framework github":
1. NousResearch/hermes-agent · GitHub - https://github.com/nousresearch/hermes-agent
2. Releases: NousResearch/hermes-agent - https://github.com/NousResearch/hermes-agent/releases
3. Hermes Agent — Open-Source AI Agent - https://hermes-agent.ai
```
`prompt_tokens: 90,550` — those 74,000 extra tokens compared to a simple question are
the search results loaded into context.

**OpenClaw response:**
```
Based on the web search for "hermes agent framework github", here are the top 3 results:
1. GitHub - NousResearch/hermes-agent: The agent that grows with you
   URL: https://github.com/nousresearch/hermes-agent
...
```
Real URLs, real search, no API key.

---

## Proving It Is the Framework, Not a Wrapper

Here is the evidence that both containers are running their full agent logic, not just
forwarding requests to NVIDIA:

**Hermes prompt tokens on a simple factual question:** `16,349`

A direct NVIDIA API call for "What is 17 × 13?" uses about 20 tokens of prompt. Those
extra 16,300 tokens are Hermes's system prompt and tool schemas — loaded on every single
request, regardless of how simple the question is. That overhead is the framework.

**Hermes executing a real terminal command:**

```
User: Run: echo HERMES_TOOL_PROOF && uname -a && date

Hermes: HERMES_TOOL_PROOF
        Linux fb851be1f14e 6.12.76-linuxkit #1 SMP Sun Mar 8 14:41:59 UTC 2026 aarch64 GNU/Linux
        Sat Aug 15 03:54:46 UTC 2026
```

That hostname is the actual Docker container ID. That kernel is Docker Desktop's Linux
kernel running on macOS. The command executed inside the container.

**OpenClaw making multiple NVIDIA calls per user request:**

From the OpenClaw internal log on a research prompt:
```
[model-fetch] start   provider=nvidia model=nvidia/nemotron-3-super-120b-a12b elapsedMs=--
[model-fetch] response provider=nvidia status=200 elapsedMs=615
[model-fetch] start   provider=nvidia model=nvidia/nemotron-3-super-120b-a12b elapsedMs=--
[model-fetch] response provider=nvidia status=200 elapsedMs=528
[model-fetch] start   provider=nvidia ...   ← third call
```

Multiple NVIDIA inference calls per user request. That is the agent reasoning loop:
call model → get tool call → execute tool → call model again with results → get answer.

---

## The Benchmark CLI

The benchmark is a Python CLI (`aab`) that orchestrates the comparison:

```bash
# Basic run
aab run "Explain the CAP theorem in 2 sentences"

# Tagged for per-category reports
aab run --tag research "What is the current state of quantum computing?"
aab run --tag coding "Write a binary search function in Python with tests"
aab run --tag devops "What does kubectl get pods -A -o wide show?"

# Review status
aab status

# Rate responses (1-5, pick preferred agent)
aab evaluate

# Generate report
aab report --days 7
```

Each `aab run` sends the same prompt to both agents sequentially, with a 2-second gap
between requests. The gap prevents 429 rate-limit errors when both share a single NVIDIA
account; with two separate accounts it is an extra safety margin.

Results are stored in SQLite — latency, token counts (where exposed), raw responses,
human ratings. Everything is local, nothing is sent anywhere.

**Connecting via Telegram:**

Since I do not always have a laptop open, I also set up a Telegram bot so I can trigger
benchmarks from my phone:

```bash
# Set token in .env: BENCH_TELEGRAM_BOT_TOKEN=...
aab telegram
```

Send any message to the bot and you get both agent responses back in chat. Prefix with
`#tag` for category tracking: `#coding Write a fibonacci function`. The bot runs the
full benchmark loop and sends both responses side by side.

---

## First Results — With a Caveat

After getting both agents working with web search enabled, I ran the first head-to-head:

> *"Search the web for what the Hermes agent framework by NousResearch does. Summarise
> in 3 sentences."*

| | Hermes | OpenClaw |
|---|---|---|
| Latency | 40.4s | 30.3s |
| Prompt tokens (visible) | 104,431 | 0 (not reported) |
| Web search used | ✅ DuckDuckGo via `ddgs` | ✅ DuckDuckGo via plugin |
| Answer quality | Detailed, cited deployment options (VPS, Modal, Daytona) | Accurate, cited official NousResearch URL |

OpenClaw was faster on this research task. Hermes loaded substantially more web content
into context — 104k tokens is multiple full web pages. Whether that extra context
produces better answers across many tasks is exactly what the 30-day benchmark will show.

**The caveat:** this result was collected with both agents using the same NVIDIA API key.
Same key means potential shared KV cache on NVIDIA's servers, which could give the
second agent unfairly fast responses when prompts have overlapping prefixes. All results
marked `[shared-key]` in the benchmark records are provisional. The production benchmark
uses two separate NVIDIA accounts.

---

## Known Limitations Going In

I want to be honest about what this benchmark does and does not measure:

**Token costs are one-sided.** Hermes exposes full token counts in the API response.
OpenClaw always returns zero — it runs multiple internal NVIDIA calls per user request
and does not surface the aggregate. Infrastructure cost (latency × cost-per-hour) is
a fairer proxy for OpenClaw.

**DuckDuckGo search quality varies.** Both agents use DuckDuckGo without authentication.
Results can differ between requests due to rate-limiting and result ranking changes.
Neither has stable, authenticated access to a search index.

**Hermes's 16k token overhead is always present.** On simple one-line questions, Hermes
pays ~16k tokens in framework overhead before the model sees any content. That overhead
is real cost and real latency. On complex multi-step tasks, it may be justified by the
richer tool context.

**Sequential execution does not eliminate all timing effects.** Even with separate NVIDIA
accounts, both containers run on the same host machine. Resource contention (CPU, network)
means the second agent's response time includes any residual system load from the first.
Over many runs this should average out.

---

## What Is Coming in Part 2

Part 2 will be the data. After 30 days of running the benchmark across four categories —
coding, research, DevOps, and writing — I will publish full results:

- Per-category win rates: which framework produces better answers for which task type?
- Latency distribution: is Hermes's tool overhead consistent or does it spike on complex tasks?
- Infrastructure cost per request at production scale
- Example pairs of responses for the same prompt, so you can judge the quality difference yourself

The questions I am most interested in:

1. Does Hermes's 16k-token system prompt buy measurably better answers, or is it overhead
   that cancels out against OpenClaw's lighter context?
2. Does OpenClaw's multi-call reasoning produce more accurate answers on research tasks?
3. Which framework handles a task that requires both web search AND a terminal command?
4. At 100 requests per day, what is the actual monthly compute cost difference?

The benchmark is open-source. If you want to run it against your own tasks before Part 2
publishes, or add a third agent framework to the comparison, the setup guide is in
[BENCHMARK.md](../BENCHMARK.md) in the repository.

*Part 2 will publish once I have 30 days of data. Follow to get notified.*

---

## Quick Setup Reference

If you want to reproduce this setup:

```bash
# 1. Clone and install
git clone <repo-url>
cd agent-assist-bench
pip install -e ".[dev]"

# 2. Configure
cp docker/hermes/.env.example docker/hermes/.env    # add NVIDIA Account A key
cp docker/openclaw/.env.example docker/openclaw/.env  # add NVIDIA Account B key
# Edit root .env: BENCH_HERMES_ENDPOINT, BENCH_OPENCLAW_ENDPOINT, API keys

# 3. Build and start
docker compose build
docker compose up -d

# 4. Enable free web search (one-time, no API keys needed)
# Hermes:
docker exec -u root hermes-agent /usr/local/bin/uv pip install ddgs \
  --target /opt/data/lazy-packages --python /opt/hermes/.venv/bin/python3
# OpenClaw:
docker exec openclaw-agent node openclaw.mjs plugins enable duckduckgo
docker compose restart openclaw

# 5. Verify both agents are healthy
curl http://localhost:8001/health   # {"status": "ok", "platform": "hermes-agent"}
curl http://localhost:8002/health   # {"ok": true, "status": "live"}

# 6. Run first benchmark
aab run --tag research "Explain the CAP theorem in 3 sentences"
aab status
```

---

*The code, Dockerfiles, configuration files, and benchmark records discussed in this
article are all in the repository. The benchmark methodology — including the web search
setup without paid API keys — is documented in full in `BENCHMARK.md`.*

---

**Tags:** `AI Agents`, `Machine Learning`, `Docker`, `Open Source`, `Developer Tools`,
`LLM`, `Benchmarking`, `Hermes`, `OpenClaw`, `NVIDIA`
