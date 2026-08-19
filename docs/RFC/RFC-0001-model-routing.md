# RFC-0001: Model Routing

**Status:** Open  
**Author:** Karan Gehlod  
**Date:** 2026-07-30  
**Related ADRs:** ADR-0007 (Agent Abstraction), ADR-0003 (Sequential Execution)

## Summary

Introduce a Model Router as a first-class architectural concept that allows agents to select models by capability tier rather than by name. This decouples agents from specific model providers and enables the benchmark to compare routing strategies as an additional evaluation dimension.

## Motivation

The current architecture (v1) assumes a fixed model per agent:

```
User → Agent → Fixed Model (Nemotron 3 550B)
```

This is sufficient for initial benchmarking, but it misses a critical insight: in production, the optimal model depends on the task. Using a 550B parameter model to generate a tweet is like hiring a senior architect to write a commit message — it works, but the cost-benefit ratio is poor.

Real-world AI assistant stacks increasingly use model routing:

```
User → Agent → Model Router → Fast | Balanced | Reasoning
```

By designing this into the architecture early (even if v1 uses a single model), we:

1. Enable future benchmarking of routing strategies
2. Keep the system provider-agnostic
3. Allow cost/latency optimization per task type
4. Add a powerful new evaluation dimension

## Proposal

### Capability Tiers (Not Size Names)

Define models by capability rather than size, because "nano" and "large" mean different things across providers:

| Tier | Optimized For | Example Tasks |
|------|--------------|---------------|
| **Fast** | Latency and cost | Classification, summaries, routing, metadata extraction, grammar correction |
| **Balanced** | Everyday work | Documentation, coding, SQL, refactoring, blog writing, planning |
| **Reasoning** | Complex planning and long-context | Browser automation, multi-step reasoning, research, complex debugging |

### Routing Policy

Agents don't hardcode model names. They declare intent, and the router resolves it:

```yaml
# config/model-routing.yaml
profiles:
  fast:
    provider: nvidia
    model: nemotron-nano
    max_tokens: 4096
    cost_per_1k_tokens: 0.001

  balanced:
    provider: nvidia
    model: nemotron-medium
    max_tokens: 16384
    cost_per_1k_tokens: 0.005

  reasoning:
    provider: nvidia
    model: nemotron-3-550b
    max_tokens: 32768
    cost_per_1k_tokens: 0.02

routing:
  summarize:
    preferred: fast
    fallback: balanced
  coding:
    preferred: balanced
    fallback: reasoning
  browser_automation:
    preferred: reasoning
    fallback: balanced
  documentation:
    preferred: balanced
  research:
    preferred: reasoning
  classification:
    preferred: fast
```

### Architecture (v2)

```
User
  ↓
Benchmark API
  ↓
Agent (Hermes / OpenClaw)
  ↓
Model Router
  ↓
┌─────────────┬──────────────┬──────────────┐
│    Fast     │   Balanced   │  Reasoning   │
└─────────────┴──────────────┴──────────────┘
```

### Interface

```python
class ModelRouter:
    """Routes model requests to appropriate tier based on task type."""

    def __init__(self, config: RoutingConfig) -> None: ...

    def resolve(self, task_type: str, override: str | None = None) -> ModelProfile:
        """Resolve a task type to a model profile."""
        ...

    def list_profiles(self) -> dict[str, ModelProfile]: ...


@dataclass
class ModelProfile:
    tier: str              # "fast", "balanced", "reasoning"
    provider: str          # "nvidia", "openai", "anthropic"
    model: str             # Provider-specific model name
    max_tokens: int
    cost_per_1k_tokens: float
```

### Benchmark Metrics Extension

When model routing is active, each execution records:

| Field | Description |
|-------|-------------|
| `selected_tier` | Which capability tier was chosen |
| `selected_model` | Actual model name used |
| `routing_reason` | Why this tier was selected (task classification) |
| `routing_latency_ms` | Time spent on routing decision |

### New Evaluation Dimension

The benchmark gains a powerful new comparison axis:

| Agent | Deployment | Cloud | **Model Tier** | Cost | Latency | Quality |
|-------|-----------|-------|----------------|------|---------|---------|
| Hermes | ACA | Azure | Fast | $0.001 | 200ms | 3/5 |
| Hermes | ACA | Azure | Balanced | $0.005 | 800ms | 4/5 |
| Hermes | ACA | Azure | Reasoning | $0.02 | 2400ms | 5/5 |

This reveals when the cheaper/faster option is "good enough."

## v1 Implementation (Minimal)

For v1, the model router exists conceptually but is trivially implemented:

```python
class StaticModelRouter(ModelRouter):
    """v1: Always returns the same model (Nemotron 3 550B)."""

    def resolve(self, task_type: str, override: str | None = None) -> ModelProfile:
        return ModelProfile(
            tier="reasoning",
            provider="nvidia",
            model="nemotron-3-550b",
            max_tokens=32768,
            cost_per_1k_tokens=0.02,
        )
```

This means:
- The interface exists from day one
- Agents interact with the router (not models directly)
- v2 can swap in a real routing implementation without changing agents
- Benchmark data already records the tier field (always "reasoning" in v1)

## v2 Implementation

- Task classification (Fast model classifies the incoming request)
- Policy-based routing from YAML config
- Fallback chains (if preferred tier is unavailable)
- Cost tracking per tier
- A/B testing: same prompt → different tiers → compare quality vs. cost

## Alternatives

1. **Hardcode model per agent** — Simpler but creates tight coupling and prevents future routing benchmarks
2. **Let agents handle routing internally** — Opaque to the benchmark; can't compare routing strategies
3. **External routing service (LiteLLM, etc.)** — Adds dependency; better to own the abstraction for benchmarking purposes
4. **Skip routing entirely** — Leaves money on the table for production deployments; misses a key evaluation dimension

## Trade-offs

### Benefits

- Provider-agnostic model selection
- Enables cost optimization benchmarking
- Clean separation of concerns (agent ≠ model selection)
- Future-proof for multi-provider support
- Minimal v1 cost (static router)

### Costs

- Slight additional abstraction layer
- Routing policy needs to be configured
- Task classification itself costs tokens (in v2)
- More complex benchmark analysis (additional dimension)

## Open Questions

1. Should the routing decision be made by the agent or by the benchmark runner?
2. How should task type be determined — explicit labels, or automatic classification?
3. Should routing policy be per-agent or global?
4. What happens when a tier is unavailable (provider outage)?
5. Should the benchmark compare "smart routing" vs. "always use large" as a strategy?

## Resolution

*(To be filled when this RFC is resolved)*

- **Decision:** Pending
- **ADR:** TBD
- **Rationale:** TBD
- **Target Version:** v0.4.0+ (after initial agent integration)
