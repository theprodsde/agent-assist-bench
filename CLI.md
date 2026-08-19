# CLI Reference

Complete command reference for AgentAssistBench.

## Commands

### `aab run`

Submit a prompt to all registered agents and store results.

**Usage:**

```bash
aab run [OPTIONS] PROMPT
```

**Options:**

- `--tag TAG` — Category tag for per-category reports. Repeatable. Examples: `coding`, `research`, `writing`, `devops`
- `--wait` — Block until all agents complete (default: async return with benchmark ID)

**Examples:**

```bash
# Simple prompt
aab run "Explain quantum computing"

# With category tags (enables per-category reports)
aab run --tag coding "Write a binary search in Python"
aab run --tag research "Explain the CAP theorem"
aab run --tag devops "How do I scale Kubernetes?"

# Multiple tags
aab run --tag coding --tag research "Analyze this algorithm and write code"

# Wait for completion
aab run --wait "Long-running task"
```

**Output:**

```
Benchmark ID: 01ARZ3NDEKTSV4RRFFQ69G5FAV
Status: pending → running → completed
Hermes response: ...
OpenClaw response: ...
```

---

### `aab status`

Show recent benchmarks and their execution status.

**Usage:**

```bash
aab status [OPTIONS]
```

**Options:**

- `--days N` — Show benchmarks from the last N days (default: 1)
- `--limit N` — Show the N most recent benchmarks (default: 20)
- `--tag TAG` — Filter by category tag

**Examples:**

```bash
# Show today's benchmarks
aab status

# Show the last 7 days
aab status --days 7

# Show only coding benchmarks
aab status --tag coding

# Show only the last 5
aab status --limit 5
```

**Output:**

```
ID                          Status      Agents  Tags
01ARZ3NDEKTSV4RRFFQ69G5FAV  completed   2/2     coding
01ARZ3NDEKTSV4RRFFQ69G5FBV  completed   2/2     research
01ARZ3NDEKTSV4RRFFQ69G5FCV  partial     1/2     devops
```

---

### `aab evaluate`

Interactively rate completed benchmarks and select preferred agents.

**Usage:**

```bash
aab evaluate [OPTIONS]
```

**Options:**

- `--benchmark-id ID` — Evaluate a specific benchmark (skip others)
- `--auto-mode` — Non-interactive (for CI/CD)

**Workflow:**

1. Shows a completed benchmark's responses from all agents
2. Prompts you to rate the benchmark (1-5 Likert scale)
3. Optionally select preferred agent and deployment
4. Saves evaluation to database

**Example:**

```bash
aab evaluate

# Shows:
# Benchmark: 01ARZ3NDEKTSV4RRFFQ69G5FAV
# Prompt: "Explain quantum computing"
# 
# Agent 1: Hermes (deployment: local_docker)
# Response: Quantum computing uses quantum bits (qubits)...
# 
# Agent 2: OpenClaw (deployment: local_docker)
# Response: Quantum computers leverage superposition and entanglement...
# 
# Rate this benchmark (1-5): 4
# Preferred agent (1=Hermes, 2=OpenClaw, skip): 2
# Notes (optional): OpenClaw better explained quantum principles
```

---

### `aab report`

Generate a Markdown report with per-category win rates and recommendations.

**Usage:**

```bash
aab report [OPTIONS]
```

**Options:**

- `--days N` — Include benchmarks from the last N days (default: 30)
- `--tags TAG [TAG ...]` — Filter to specific categories
- `--output FILE` — Write to file (default: stdout)
- `--min-samples N` — Minimum samples per category for recommendation (default: 5)

**Examples:**

```bash
# 30-day report
aab report

# Last 7 days
aab report --days 7

# Only coding and research
aab report --tags coding research

# Save to file
aab report --output report.md
```

**Output:**

```markdown
# AgentAssistBench Report (2026-08-19)

**Benchmarks Evaluated:** 418
**Period:** Last 30 days

## Summary by Category

| Category | Samples | Best Agent | Win Rate | Avg Latency | Avg Cost |
|----------|---------|------------|----------|-------------|----------|
| coding | 98 | Hermes | 89% | 3.2s | $0.004 |
| research | 107 | OpenClaw | 73% | 8.1s | $0.009 |
| writing | 156 | OpenClaw | 94% | 5.7s | $0.007 |
| devops | 57 | Hermes | 97% | 2.8s | $0.003 |

## Recommendations

- **Coding & DevOps:** Use Hermes on local_docker (fastest, cheapest)
- **Research & Writing:** Use OpenClaw on managed_container (best quality)
- **General:** Hermes for simple tasks, OpenClaw for multi-step reasoning
```

---

### `aab telegram`

Start an interactive Telegram bot for benchmarking from chat.

**Setup:**

1. Create a bot with [@BotFather](https://t.me/botfather) on Telegram
2. Add to `.env`:

```env
BENCH_TELEGRAM_BOT_TOKEN=123456789:ABCdefGhijklmno
```

3. Start the bot:

```bash
aab telegram
```

4. Send messages to your bot. It will:
   - Run the benchmark
   - Send both agent responses back

**Message Syntax:**

```
Plain message:
  Explain machine learning

With tags:
  #coding Write a quicksort in Rust
  #research #coding Compare sorting algorithms
```

Tags are stripped from the prompt before reaching agents and stored for report grouping.

**Limitations:**

- Telegram max message length is 4096 chars (responses truncated with `…` but full text stored in DB)
- No concurrency guard — send one prompt at a time
- Blocks until Ctrl-C (run in `tmux`/`screen` for production)

---

## Configuration

All CLI commands use environment variables (or `.env` file). See [DEPLOYMENT.md](DEPLOYMENT.md) for full reference.

Key variables:

```env
BENCH_HERMES_ENDPOINT=http://localhost:8001/v1
BENCH_OPENCLAW_ENDPOINT=http://localhost:8002/v1
BENCH_HERMES_API_KEY=xxx
BENCH_OPENCLAW_API_KEY=xxx
BENCH_DB_PATH=storage/benchmark.db
```

---

## Combining Commands

Typical workflow:

```bash
# 1. Run a batch of benchmarks (tagging for categories)
aab run --tag coding "Write a binary search"
aab run --tag coding "Sort an array"
aab run --tag research "Explain monads"
aab run --tag research "What is functor?"

# 2. Check status
aab status --days 1

# 3. Evaluate completed benchmarks
aab evaluate

# 4. Generate report
aab report --days 7 --output weekly-report.md

# 5. Push report to GitHub/Slack
cat weekly-report.md | pbcopy  # macOS
# or
wc -c weekly-report.md
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration error (missing .env, invalid endpoint) |
| 2 | Validation error (prompt too long, invalid tag) |
| 3 | Execution error (agent timeout, health check failed) |
| 4 | Storage error (database locked, disk full) |
| 5 | User error (no benchmarks to evaluate, invalid rating) |
