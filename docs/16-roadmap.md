# 16 — Roadmap

## Development Philosophy

Ship fast, prove the idea. The MVP validates the core loop (capture → execute → store → report). Infrastructure and input channels come after the core is proven useful.

## MVP (2-3 Weeks)

The minimum viable benchmark that proves the core thesis:

| Component | Description |
|-----------|-------------|
| CLI | `aab run "prompt"` — submit benchmarks from command line |
| Runner | Sequential execution across configured agents |
| SQLite | Storage for benchmarks, executions, evaluations |
| Adapter Interface | Plugin protocol for agents |
| OpenAI-compatible Adapter | Default — works with most agents out of the box |
| Hermes Adapter | Custom adapter for Hermes |
| OpenClaw Adapter | Custom adapter for OpenClaw |
| Report Generator | Duration-based comparison report (Markdown) |
| Weekly Review | Batch evaluation UI/CLI |

**Nothing else.** No REST API. No Telegram. No Terraform. Prove the idea.

## Post-MVP Phases

| Phase | Scope | Timeline |
|-------|-------|----------|
| v0.2 | REST API + Docker + Terraform (local) | +2 weeks |
| v0.3 | VM + Managed Container + Infrastructure metrics | +2 weeks |
| v0.4 | Telegram + Discord + Model routing | +2 weeks |
| v1.0 | Dashboard + Weekly reviews UI + Long-term analytics | +3 weeks |

## Plugin Architecture (From Day One)

```
plugins/
├── agents/         # Agent adapters
│   ├── openai_compatible/
│   ├── hermes/
│   ├── openclaw/
│   └── ...
├── deployments/    # Deployment plugins
│   ├── local/
│   ├── vm/
│   └── container/
└── evaluators/     # Evaluation plugins
    ├── human/
    └── ...
```

## Estimated PR Plan (MVP)

```
PR-001  Repository setup, pyproject.toml, plugin architecture skeleton
PR-002  Core models (Pydantic), SQLite schema, storage manager
PR-003  Agent adapter protocol + OpenAI-compatible adapter
PR-004  Benchmark runner (sequential execution)
PR-005  Hermes adapter
PR-006  OpenClaw adapter
PR-007  CLI tool (aab run, aab status, aab evaluate)
PR-008  Report generator (Markdown comparison report)
PR-009  Weekly batch evaluation CLI
PR-010  Integration tests + property-based tests
```

## Input Layer Progression

```
MVP:     CLI only (aab run "prompt")
v0.2:    REST API (POST /benchmarks)
v0.4:    Telegram bot
v0.4:    Discord bot
Future:  Slack, browser extension, IDE plugin
```

The benchmark runner never knows who submitted the request — all channels use the same internal API.

## Versioning

| Version | Milestone |
|---------|-----------|
| v0.1.0 | MVP — CLI + Runner + Report |
| v0.2.0 | REST API + Docker |
| v0.3.0 | Terraform + Multi-deployment |
| v0.4.0 | Messaging + Model routing |
| v1.0.0 | Stable release with dashboard |

---

→ Previous: [15 — Testing Strategy](15-testing-strategy.md)  
→ Back to: [Documentation Index](README.md)
