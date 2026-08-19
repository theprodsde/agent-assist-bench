# ADR-0010: Real Workload Benchmarking

**Status:** Accepted  
**Date:** 2026-07-30

## Context

This is the defining decision for AgentAssistBench — the one that makes it unique.

Traditional AI benchmarks define synthetic tasks upfront:

- SWE-bench: Pre-selected GitHub issues with known fixes
- WebArena: Scripted browser interactions with expected outcomes
- GAIA: Curated multi-step reasoning questions
- HumanEval: Code generation problems with test cases

These benchmarks are valuable for research but share a fundamental limitation: they measure performance on curated tasks, not on the messy, diverse, unpredictable tasks that engineers actually encounter daily.

Real engineering work includes:

- Debugging a Docker networking issue at 2am
- Drafting a technical blog post
- Researching a new library's API
- Writing a code review response
- Generating Terraform for a new resource
- Automating a browser workflow for data collection
- Summarizing a research paper
- Drafting an email to a vendor

No synthetic benchmark captures this diversity.

## Decision

The benchmark does not define synthetic tasks. Instead, every natural interaction with an AI assistant becomes a benchmark case.

### How It Works

1. User works normally — asks questions, requests code, automates tasks
2. Each interaction is automatically captured as a benchmark request
3. The same request is dispatched to all configured agents
4. Results are stored side-by-side for later evaluation
5. Over time, patterns emerge about which agent excels at which task type

### Task Categories (Emergent, Not Predefined)

Tasks are tagged after the fact, not designed before:

| Category | Example |
|----------|---------|
| Coding | "Write a Python function that validates email addresses" |
| Debugging | "Why is my Docker container exiting with code 137?" |
| Research | "Compare Redis vs. Memcached for session storage" |
| Documentation | "Write API documentation for this endpoint" |
| Browser automation | "Scrape pricing data from this comparison page" |
| DevOps | "Generate Terraform for an Azure Container App" |
| Communication | "Draft a technical RFC for this architecture change" |
| Analysis | "Summarize the key findings from this paper" |

### Properties of Real Workload Benchmarking

- **Unscripted** — Tasks are not designed for evaluation
- **Diverse** — Covers the full range of engineering work
- **Evolving** — New task types emerge as work changes
- **Personal** — Reflects one engineer's actual needs
- **Longitudinal** — Accumulates over days, weeks, months
- **Contextual** — Tasks may reference previous conversations

## Consequences

### Positive

- Results are directly relevant to the user's actual work
- No effort spent designing or maintaining synthetic tasks
- Naturally captures task diversity
- Benchmark improves over time as data accumulates
- Reveals agent strengths/weaknesses for specific task types
- Zero additional effort from the user (just work normally)

### Negative

- Results are personal — may not generalize to other users
- No ground truth — cannot automatically determine "correct" answers
- Task distribution is uncontrolled (may be heavy on one type)
- Privacy concerns — real prompts may contain sensitive information
- Harder to compare across users or time periods
- Small sample sizes early on

### Mitigations

- Human evaluation compensates for lack of ground truth (ADR-0005)
- Tags enable filtering and analysis by task type
- Export format allows anonymization before sharing
- Longitudinal data reveals trends despite early small samples
- Optional: users can exclude specific interactions from benchmarking

## Alternatives Considered

1. **Use GAIA dataset** — Rejected because it tests general reasoning, not daily engineering workflows
2. **Use WebArena tasks** — Rejected because it only covers browser automation, not the full range of engineering work
3. **Create custom synthetic tasks** — Rejected because maintaining a task dataset requires ongoing effort and still won't match real usage patterns
4. **Hybrid (real + synthetic)** — Considered for future versions; rejected for v1 to maintain focus and simplicity
5. **Record and replay** — Considered (record real interactions, replay later) but rejected because it adds complexity without clear benefit over live capture

## References

- [Observational Studies vs. Controlled Experiments](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3049418/)
- [Production Workload Characterization](https://research.google/pubs/pub49065/)
- [Experience Sampling Method](https://en.wikipedia.org/wiki/Experience_sampling_method)
