# 01 — Problem Statement

## The Gap in Current AI Benchmarking

The AI ecosystem has produced numerous benchmarks for evaluating language models and AI agents. These benchmarks serve important research purposes but leave a critical gap for practicing engineers.

## What Existing Benchmarks Answer

| Benchmark | Question It Answers |
|-----------|-------------------|
| GAIA | Can the model reason across multiple steps? |
| SWE-bench | Can the model fix real GitHub issues? |
| WebArena | Can the agent navigate websites? |
| BrowserArena | Can the agent complete browser tasks? |
| HumanEval | Can the model generate correct code? |
| MMLU | Does the model have broad knowledge? |

## What Engineers Actually Want to Know

1. **Which AI assistant helps me most during daily work?**
   - Not on curated tasks, but on the messy, diverse, unpredictable problems that actually come up.

2. **Should I deploy it on a VM or a managed container?**
   - Cold start differences, latency profiles, cost implications.

3. **Which deployment is the most cost-effective?**
   - Per-request cost across different infrastructure configurations.

4. **Which agent performs browser automation more reliably?**
   - Not on scripted scenarios, but on real websites with real variability.

5. **Which setup gives me the best experience over weeks of real usage?**
   - Long-term reliability, consistency, and satisfaction — not one-shot benchmarks.

## Why This Gap Exists

### 1. Academic vs. Engineering Focus

Academic benchmarks prioritize:
- Controlled conditions
- Reproducibility across labs
- Statistical significance
- Ground truth labels

Engineering decisions require:
- Real-world conditions
- Reproducibility in your environment
- Practical significance (does it help me?)
- Subjective quality (is this response useful?)

### 2. Point-in-Time vs. Continuous Evaluation

Most benchmarks run once and produce a score. But agent quality varies:
- By task type (coding vs. research vs. documentation)
- By time of day (API latency, model load)
- By deployment type (cold start, resource constraints)
- Over time (model updates, infrastructure changes)

A single benchmark run cannot capture these dynamics.

### 3. Synthetic vs. Natural Tasks

Synthetic tasks have known correct answers. Real engineering work often doesn't:
- "Is this code review feedback helpful?" — subjective
- "Is this documentation clear?" — depends on audience
- "Is this debugging approach efficient?" — depends on context
- "Is this email well-written?" — depends on tone requirements

## The Core Problem Statement

> There is no open-source framework that continuously evaluates AI assistant **ecosystems** (agent + model + deployment + infrastructure) using real engineering workflows, compares them across multiple dimensions, and relies on human judgment to determine quality over time.

People don't choose "Hermes" in isolation — they choose a complete setup. The benchmark evaluates that complete setup.

## What AgentAssistBench Provides

| Need | Solution |
|------|----------|
| Ecosystem evaluation | Five dimensions: Agent, Deployment, Model, Task, Human |
| Real workload data | Every natural interaction becomes a benchmark case |
| Duration-based insights | Run for a week/month, get per-category recommendations |
| Multi-agent comparison | Same prompt fanned out to all configured agents |
| Deployment comparison | Same agent tested across infrastructure configurations |
| Reproducible infrastructure | Terraform makes deployment comparisons repeatable |
| Human-aligned quality | Weekly batch evaluation — you rate, not an LLM |
| Actionable reports | Per-category recommendations, not a single score |

## Success Criteria

AgentAssistBench succeeds if:

1. A single engineer can run it alongside their normal workflow
2. After 2-4 weeks of data, clear agent/deployment preferences emerge
3. The data supports evidence-based decisions about AI tooling
4. The setup is reproducible by anyone following the documentation
5. The benchmark produces content suitable for technical communication

---

→ Previous: [00 — Project Overview](00-project-overview.md)  
→ Next: [02 — Goals & Non-Goals](02-goals-and-non-goals.md)
