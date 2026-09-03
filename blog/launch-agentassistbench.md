# I Got Tired of Benchmarks That Test Models Instead of Agent Frameworks, So I Built My Own

*Published by TheProdSDE · github.com/theprodsde/agent-assist-bench*

---

Every time I evaluated an AI agent framework for daily work, I ran into the same wall.

I'd look up benchmarks. GAIA, SWE-bench, WebArena — impressively rigorous, completely
irrelevant to my question. Those benchmarks tell you which *model* is best at a
predefined set of tasks curated by researchers. That's not the question I was asking.

My question was: **between these two specific agent stacks, both running the same
underlying LLM, which one is actually better for my daily engineering work?**

Nobody had an answer. So I built one.

---

## The Key Insight Most Benchmarks Miss

When you pick an AI assistant for daily use, you're not picking a model. You're picking
a full stack:

- The **system prompt** that shapes how the model interprets your request
- The **tool routing logic** that decides when to search the web, run code, or read a file
- The **memory architecture** that determines how well it handles multi-step tasks
- The **infrastructure** that controls whether a response takes 2 seconds or 40

Two frameworks running the exact same LLM — say, both pointing at the same Ollama
endpoint serving llama3 — can produce wildly different outputs for the same prompt. The
framework's contribution to quality, latency, and cost is enormous. And nobody was
measuring it.

The closest thing is Chatbot Arena, which has humans compare model outputs. But it
compares *models*, not frameworks. It uses crowd-level preference, not your specific
workload. And it tells you nothing about latency or infrastructure cost.

---

## What I Built

**AgentAssistBench** is an open-source CLI that runs your actual daily tasks against
any number of OpenAI-compatible agent frameworks side-by-side, stores the results
locally in SQLite, and after 30 days generates a report like this:

```
Category    │ Best Stack      │ Win Rate │ Avg Latency │ Avg Cost/req │
────────────┼─────────────────┼──────────┼─────────────┼──────────────┤
coding      │ hermes          │  68.4%   │    4.2 s    │   $0.0031    │
research    │ openclaw        │  59.1%   │    8.1 s    │   $0.0062    │
devops      │ hermes          │  72.2%   │    3.9 s    │   $0.0028    │
writing     │ openclaw        │  62.5%   │    9.4 s    │   $0.0071    │
```

That's not a synthetic score. That's my actual coding prompts, my actual research
questions, run against both frameworks, rated by me. 94 benchmarks over 30 days.

The recommendation: use hermes for coding and devops, use openclaw for research and
writing. Different frameworks win on different categories. That split recommendation
is something no leaderboard would ever surface.

---

## Three Design Decisions That Make It Different

### 1. Human evaluation only — no LLM-as-judge

Every evaluation is done by me, rating responses 1–5. No automated scoring. This was
a deliberate choice.

LLM-as-judge is convenient but circular — you're using one model's preferences to
decide which model is better. If you've ever seen a GPT-4 judge reliably prefer
GPT-4 outputs, you understand the problem. My preferences for what counts as a good
coding answer are not the same as any model's.

`aab evaluate` shows both responses side by side and asks me which I preferred. That's
it. The win rate in the report reflects what I actually found useful.

### 2. The same LLM, different frameworks

Both frameworks in my setup call the same underlying model — NVIDIA Nemotron via the
same API endpoint. This is the controlled variable. When Hermes beats OpenClaw on a
coding task, I know it's not because Hermes happened to get a better model that day.

This is the benchmark equivalent of A/B testing: hold everything constant except the
thing you're measuring.

### 3. 30 days of real tasks, not a curated test set

I don't submit benchmark prompts. I submit the prompts I was already going to ask. Each
morning I tag tasks with a category and run them through both frameworks:

```bash
aab run --tag coding "Refactor this Python function to use dataclasses instead of namedtuples"
aab run --tag devops "Write a Dockerfile for a FastAPI app with uv and non-root user"
aab run --tag research "Compare WAL mode vs journal mode in SQLite for concurrent reads"
```

After 30 days I have 90+ data points across categories. The report surfaces patterns
I wouldn't have noticed from casual use — like the fact that OpenClaw consistently
writes better prose but Hermes is faster and more precise for structured tasks.

---

## How It Works Technically

The architecture is deliberately simple:

```
You → aab run --tag coding "prompt"
         ↓
    BenchmarkRunner
    (sequential execution)
         ↓
    Agent 1 → POST /v1/chat/completions → record latency + tokens + cost
    Agent 2 → POST /v1/chat/completions → record latency + tokens + cost
         ↓
    SQLite (benchmarks + executions)
         ↓
    aab evaluate → you rate 1–5, pick winner
         ↓
    aab report → per-category win rates, latency, cost, recommendations
```

Every agent is just an HTTP endpoint behind the OpenAI chat completions API contract.
This is intentional — it means the tool works with anything: Ollama, vLLM, LibreChat,
Open WebUI, LiteLLM, a proxied OpenAI key, or a completely custom setup.

### Adding any OpenAI-compatible agent

No code required. Drop this into `.env`:

```env
BENCH_AGENTS_JSON=[
  {"name":"ollama-llama3","endpoint":"http://localhost:11434/v1","model":"llama3"},
  {"name":"librechat","endpoint":"http://localhost:9000/v1","model":"gpt-4o","api_key":"sk-..."}
]
```

Run `aab run "your prompt"` and both agents get the prompt. That's the entire setup.

### What gets measured per execution

For every agent response the runner stores:

- **Total latency** in milliseconds (from request sent to response parsed)
- **Prompt tokens, completion tokens, total tokens** (from the usage field)
- **Estimated cost in USD** (from the response or from cost-per-hour × duration)
- **Success / failure** with full error text if the agent timed out or returned an error
- **Cold start time** from the health check before the request

This data drives the per-category cost comparison in the report. It's the only way to
make a fair cost argument — framework A might have a higher API cost per token but
faster completion, so the total cost per useful response might actually be lower.

---

## The Telegram Bot

Running `aab run` from a terminal is fine for deliberate benchmarks. But most of my
actual work happens throughout the day on my phone.

So there's a Telegram bot:

```env
BENCH_TELEGRAM_BOT_TOKEN=your-botfather-token
BENCH_TELEGRAM_ALLOWED_CHAT_IDS=your-numeric-id
```

```bash
uv run aab telegram
```

Now I message my bot from my phone exactly the way I'd message any AI assistant:

```
#coding Write a Python context manager for temporary file cleanup
```

The bot runs it through both agents and replies with both responses in the same
chat, side by side. I read both, make a mental note of which I preferred, and later
run `aab evaluate` to record the rating.

The `BENCH_TELEGRAM_ALLOWED_CHAT_IDS` restriction is important — it locks the bot to
your Telegram ID only. Anyone else who messages it gets silently ignored.

---

## What I Learned After 30 Days

A few things that surprised me from the first month of data:

**Framework wins are category-specific.** I expected one framework to be consistently
better. Instead, Hermes wins on structured/technical tasks and OpenClaw wins on
prose-heavy tasks. If I had just used one framework and rated it informally, I'd have
missed this split entirely.

**Latency matters more than I thought.** A 4-second response vs a 9-second response
sounds minor. But across 3–4 queries in a debugging session, that difference compounds.
The report surfaces this in a way casual use never would.

**Win rate stabilises around 40 benchmarks per category.** With fewer than ~20 in a
category, a 60/40 split is noise. Volume matters before the numbers mean anything —
`aab report --days 7` gives you an early read, but 30+ days per category is where
results stabilise. The `--days` flag is configurable; use whatever period you have.

**Cost differences are real but rarely the deciding factor.** The cheapest agent per
request isn't always the one I'd choose. Quality wins matter more. But the cost column
in the report is useful for the conversation: "I prefer OpenClaw for research, and it
costs $0.006 per request vs $0.004 for Hermes — that's acceptable."

---

## Try It

```bash
git clone https://github.com/theprodsde/agent-assist-bench.git
cd agent-assist-bench
uv sync
cp .env.example .env
# edit .env — add your agent endpoints
aab run --tag coding "Write a binary search in Python"
aab status
aab evaluate
aab report
```

The full workflow from install to first benchmark takes under 5 minutes. Use
`--days 7` for an early read after a week, `--days 30` for stronger signal.
The report only becomes meaningful with volume — run it on your real daily tasks.

Repo: [github.com/theprodsde/agent-assist-bench](https://github.com/theprodsde/agent-assist-bench)

Discussions are open for questions, results comparisons, and new framework requests.
If you're benchmarking a framework I haven't tried, share your 30-day numbers in
[Discussions](https://github.com/theprodsde/agent-assist-bench/discussions) — that
data is more useful to me than anything I could generate myself.

---

## What's Next

The MVP covers the core loop: submit → execute → evaluate → report. The roadmap has
three near-term additions:

- **REST API (v0.2)** — so the benchmark runner can be triggered from other tools and
  automation pipelines, not just the CLI
- **VM + cloud deployment (v0.3)** — Terraform configs for running agents on VMs and
  managed containers (Azure Container Apps, Cloud Run), with infrastructure cost
  tracked automatically from actual billing data
- **Dashboard UI (v1.0)** — a local web UI replacing the CLI for evaluation and
  report browsing, with per-benchmark diffs, trend charts, and 90-day history

The thing I'm most interested in is the 90-day longitudinal view. Frameworks update
constantly. A framework that loses in month 1 might win in month 3 after a significant
update. That time-series data doesn't exist anywhere else.

---

*AgentAssistBench is MIT licensed, self-hosted, and takes about 5 minutes to set up.
Built by [TheProdSDE](https://github.com/TheProdSDE).*

*Star the repo if you find it useful — and share your 30-day results when you have them.*
