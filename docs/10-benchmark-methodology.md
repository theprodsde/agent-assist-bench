# 10 — Benchmark Methodology

*Status: To be detailed in Phase 0*

## Philosophy

The benchmark evaluates the complete system rather than only the LLM.

## Evaluation Dimensions

| Dimension | What It Measures |
|-----------|-----------------|
| Agent quality | Response usefulness and correctness |
| Deployment performance | Latency, cold start, reliability |
| Infrastructure cost | Estimated USD per request |
| Browser automation | Task completion for web workflows |
| User satisfaction | Human rating (1-5 scale) |

## Methodology

- Real workloads only (ADR-0010)
- Sequential execution (ADR-0003)
- Human evaluation (ADR-0005)
- Fixed LLM model across comparisons

## Controls

- Same prompt to all agents
- Same model (Nemotron 3 550B) where possible
- Sequential execution eliminates interference
- Timing metrics collected per execution

---

→ Previous: [09 — Storage Design](09-storage-design.md)  
→ Next: [11 — Agent Interface](11-agent-interface.md)
