# 03 — Functional Requirements

*Status: To be detailed in Phase 0*

## Overview

This document will define every capability the system must have, organized by component.

## Requirement Categories

### Input Handling (FR-1xx)

- FR-101: System shall accept benchmark requests via REST API
- FR-102: System shall accept benchmark requests from Telegram bot
- FR-103: System shall accept benchmark requests from Discord bot
- FR-104: System shall accept benchmark requests from CLI tool
- FR-105: System shall support text prompts up to 100,000 characters
- FR-106: System shall support image attachments
- FR-107: System shall support audio attachments
- FR-108: System shall support document attachments
- FR-109: System shall support URL attachments

### Benchmark Execution (FR-2xx)

- FR-201: System shall generate a unique ULID for each benchmark
- FR-202: System shall execute agents sequentially (ADR-0003)
- FR-203: System shall apply configurable delay between executions
- FR-204: System shall enforce per-execution timeout
- FR-205: System shall continue execution if one agent fails
- FR-206: System shall collect timing metrics for each execution
- FR-207: System shall collect LLM metrics (tokens, model, cost) when available
- FR-208: System shall record cold start time for each execution
- FR-209: System shall support configurable execution order

### Agent Management (FR-3xx)

- FR-301: System shall support agent registration at startup
- FR-302: System shall support health check for each agent-deployment pair
- FR-303: System shall support multiple deployment types per agent
- FR-304: System shall implement the AgentAdapter protocol (ADR-0007)
- FR-305: System shall support Hermes agent adapter
- FR-306: System shall support OpenClaw agent adapter

### Storage (FR-4xx)

- FR-401: System shall persist benchmarks in SQLite (ADR-0004)
- FR-402: System shall persist execution results with full metrics
- FR-403: System shall persist human evaluations
- FR-404: System shall support querying benchmarks by status
- FR-405: System shall support querying benchmarks by date range
- FR-406: System shall support querying benchmarks by source
- FR-407: System shall support pagination for list queries

### Evaluation (FR-5xx)

- FR-501: System shall accept human evaluation for completed benchmarks
- FR-502: System shall enforce rating scale of 1-5
- FR-503: System shall record preferred agent (optional)
- FR-504: System shall record preferred deployment (optional)
- FR-505: System shall record evaluator notes (optional)
- FR-506: System shall enforce one evaluation per benchmark
- FR-507: System shall only accept evaluation for completed/partially-failed benchmarks

### Export (FR-6xx)

- FR-601: System shall export daily data as JSONL
- FR-602: System shall export daily data as CSV (separate files per table)
- FR-603: System shall generate export manifest with counts
- FR-604: System shall support manual export trigger via API
- FR-605: System shall support scheduled export (cron)
- FR-606: Export shall be idempotent (re-running overwrites)

### API (FR-7xx)

- FR-701: POST /benchmarks — Create benchmark (returns 202)
- FR-702: GET /benchmarks — List benchmarks with filtering
- FR-703: GET /benchmarks/{id} — Get benchmark details
- FR-704: GET /benchmarks/{id}/results — Get execution results
- FR-705: POST /benchmarks/{id}/evaluation — Submit evaluation
- FR-706: GET /health — System health check
- FR-707: POST /export/{date} — Trigger manual export

---

→ Previous: [02 — Goals & Non-Goals](02-goals-and-non-goals.md)  
→ Next: [04 — Non-Functional Requirements](04-non-functional-requirements.md)
