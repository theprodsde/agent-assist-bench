# 00 — Project Overview

## What is AgentAssistBench?

AgentAssistBench is an open-source evaluation framework that helps you compare AI assistant ecosystems against your own real-world workflow, enabling evidence-based decisions about agents, models, deployments, and operational cost.

Before you commit to an AI agent ecosystem for your daily work, run this benchmark against your actual tasks for a week or a month. At the end, you have data-driven evidence of which setup works best *for you* — not based on synthetic benchmarks or vibes, but on structured comparison over time.

## Why Does It Exist?

Today's AI ecosystem can tell you which LLM scores highest on academic benchmarks. But engineers need answers to different questions:

- Which AI assistant ecosystem helps me every day?
- Which agent's internals (tool use, planning, reasoning) work best for my task types?
- Should I deploy it on a VM or a managed container?
- Which deployment is the most cost-effective?
- Which setup gives me the best experience over weeks of real usage?

No existing benchmark answers these questions because they require evaluating the *complete stack* — not just the model.

## The Five Dimensions

AgentAssistBench evaluates five independent dimensions rather than producing a single score:

| Dimension | What It Evaluates |
|-----------|------------------|
| **Agent** | Which agent's internals (tool use, planning, context handling) work best for this task type? |
| **Deployment** | How does infrastructure choice affect performance, reliability, and cost? |
| **Model** | Is a fast/cheap model sufficient, or does this task need a reasoning model? |
| **Task** | Which categories does each ecosystem dominate? |
| **Human** | What does the user actually prefer after reviewing outputs? |

## Who Is It For?

| Persona | Goal | Interaction |
|---------|------|-------------|
| **Developer** | Run the benchmark against their daily tasks, get a report | CLI, API |
| **Evaluator** | Compare agent ecosystems over time before committing | Telegram, Discord, Web |
| **Contributor** | Add new agent adapters, deployment targets, or evaluators | Git, Python plugins |

## The Plugin Architecture

The benchmark never directly knows any specific agent. Everything is a plugin:

```
plugins/
├── agents/        # hermes, openclaw, openai-compatible, ...
├── deployments/   # local, vm, container
└── evaluators/    # human, rule-based, future automated
```

Any agent exposing an OpenAI-compatible API works immediately. Custom agents implement a ~20 line adapter interface.

## What You Get (The Report)

After running for N days, the benchmark produces actionable recommendations:

```
30 Days — 418 Requests Evaluated

Category    | Best Agent  | Win Rate | Avg Cost
------------|-------------|----------|----------
Coding      | Hermes      | 89%      | $0.004/req
Research    | OpenClaw    | 73%      | $0.008/req
Writing     | OpenClaw    | 94%      | $0.006/req
Browser     | Hermes      | 97%      | $0.012/req

Recommendation:
  → Coding & Browser: Hermes on Managed Container
  → Writing & Research: OpenClaw on VM
  → Estimated monthly cost: $12.40
```

## Scope

### In Scope (v1)

- Sequential benchmark execution across multiple agent-deployment pairs
- Plugin architecture for agents, deployments, evaluators
- OpenAI-compatible default adapter (covers most agents)
- SQLite storage with daily JSONL/CSV exports
- Human evaluation with weekly batch review
- Duration-based comparison reports
- CLI-first interface (REST API in v0.2)
- Local Docker, VM, and Managed Container deployment types
- Terraform for reproducible infrastructure

### Out of Scope (v1)

- Kubernetes, Redis, PostgreSQL, vector databases
- Distributed execution
- Multi-user authentication
- Academic benchmark leaderboards
- Automatic quality scoring (LLM-as-judge as default)
- Production-grade dashboards

## Documentation Map

This document is part of a series. Continue reading in order:

→ Next: [01 — Problem Statement](01-problem-statement.md)
