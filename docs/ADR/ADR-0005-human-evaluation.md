# ADR-0005: Human Evaluation

**Status:** Accepted  
**Date:** 2026-07-30

## Context

AgentAssistBench captures responses from multiple AI agents for the same prompt. The fundamental question is: how do we determine which response is "better"?

Current automated evaluation approaches have significant limitations:

- **LLM-as-judge** — Introduces bias from the judge model, inconsistent across runs, expensive at scale
- **BLEU/ROUGE scores** — Measure surface-level similarity, not usefulness
- **Code execution tests** — Only applicable to coding tasks, not general engineering workflows
- **Embedding similarity** — Measures semantic closeness, not quality or correctness

For daily engineering tasks (debugging, documentation, research, code review), no automated metric reliably captures whether a response actually helped the user.

## Decision

The benchmark records agent outputs but defers quality assessment entirely to human review.

### Evaluation Data Model

Each benchmark receives at most one human evaluation containing:

| Field | Type | Description |
|-------|------|-------------|
| rating | Integer 1-5 | Overall response quality |
| preferred_agent | String (optional) | Which agent produced the best response |
| preferred_deployment | Enum (optional) | Which deployment type was preferred |
| notes | Text (optional) | Free-form evaluator observations |
| evaluator | String (optional) | Who performed the evaluation |

### Rating Scale

| Score | Meaning |
|-------|---------|
| 1 | Unusable — response is wrong, harmful, or irrelevant |
| 2 | Poor — partially relevant but mostly unhelpful |
| 3 | Acceptable — gets the job done but not impressive |
| 4 | Good — helpful, correct, well-structured |
| 5 | Excellent — exceeds expectations, saves significant time |

### Evaluation Workflow

1. Benchmark executes across all agent-deployment pairs
2. Results are stored with full agent outputs
3. Evaluator reviews all responses side-by-side
4. Evaluator submits rating, preference, and notes
5. Evaluation is immutable once submitted (no updates)

## Consequences

### Positive

- Evaluation reflects actual user satisfaction
- No automated bias from judge models
- Simple to implement and understand
- Captures subjective quality that metrics miss
- Evaluator learns which agents work best for their workflow
- Results are personally meaningful, not abstract scores

### Negative

- Evaluation is subjective — different evaluators may rate differently
- Time-consuming — requires manual review of each benchmark
- Not scalable to thousands of benchmarks per day
- Results are personal rather than universally comparable
- Evaluation may lag behind execution (days later)

### Mitigations

- Single-user design means subjectivity is consistent (same person evaluates)
- Daily export preserves evaluation data for trend analysis
- Future RFC may explore optional LLM-assisted pre-screening
- Evaluation is optional — benchmarks can exist without evaluation

## Alternatives Considered

1. **LLM-as-judge (GPT-4, Claude)** — Rejected because it introduces model bias, costs money per evaluation, and may not align with the user's actual preferences
2. **Automated code execution tests** — Rejected because most benchmark tasks are not purely code (research, documentation, debugging)
3. **A/B testing with implicit signals** — Rejected because the system is single-user and there's no implicit signal to capture
4. **Elo rating system** — Considered for future versions but rejected for v1 due to complexity; requires many comparisons to be meaningful
5. **No evaluation** — Rejected because raw outputs without quality assessment don't help with decision-making

## References

- [Chatbot Arena (LMSYS)](https://chat.lmsys.org/) — Human preference-based LLM evaluation
- [RLHF: Reinforcement Learning from Human Feedback](https://arxiv.org/abs/2203.02155)
- [Likert Scale Best Practices](https://www.simplypsychology.org/likert-scale.html)
