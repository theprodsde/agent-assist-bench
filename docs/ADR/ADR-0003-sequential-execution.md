# ADR-0003: Sequential Execution

**Status:** Accepted  
**Date:** 2026-07-30

## Context

AgentAssistBench routes each benchmark request to multiple agent-deployment pairs (e.g., Hermes ACA, Hermes VM, OpenClaw ACA, OpenClaw VM). The execution strategy—parallel vs. sequential—significantly impacts measurement quality and system complexity.

Running four deployments simultaneously introduces several challenges:

- Increased likelihood of API rate limiting (429 responses)
- Harder to isolate performance measurements per agent
- Network contention may skew latency measurements
- Debugging failures becomes more complex
- Log correlation across concurrent executions is difficult

## Decision

Execute agent-deployment pairs sequentially with configurable delays between each execution.

### Execution Order (Default)

```
Hermes — Managed Container
    ↓ (delay)
Hermes — VM
    ↓ (delay)
OpenClaw — Managed Container
    ↓ (delay)
OpenClaw — VM
```

### Configuration

```python
@dataclass
class RunnerConfig:
    execution_order: list[tuple[str, DeploymentType]]
    delay_between_seconds: float = 2.0   # Configurable
    timeout_seconds: float = 300.0       # Per execution
    retry_count: int = 0                 # No retries by default
```

### Behavior

- Delay is applied between executions, not before the first
- If one agent fails, execution continues to the next
- Timeout is enforced per execution (not globally)
- Execution order is configurable (not hardcoded)

## Consequences

### Positive

- Cleaner, more isolated measurements per agent
- Lower chance of 429 (rate limit) responses
- Easier debugging — one execution at a time
- Simpler log correlation
- No need for concurrent execution infrastructure
- Reproducible timing measurements

### Negative

- Longer overall benchmark duration (minutes vs. seconds)
- Cannot measure how agents perform under concurrent load
- Sequential bottleneck if many benchmarks are queued

### Mitigations

- Delay is configurable (can be reduced to 0 for local testing)
- Future RFC may propose optional parallel mode for load testing
- Background task execution means the API responds immediately (202 Accepted)

## Alternatives Considered

1. **Parallel execution** — Rejected because it introduces measurement noise, rate limiting risk, and debugging complexity without proportional benefit for a single-user benchmark
2. **Configurable parallel/sequential** — Rejected for v1 to keep complexity low; may be revisited via RFC
3. **Round-robin with jitter** — Rejected because it adds randomness that makes results harder to reproduce

## References

- [Rate Limiting Best Practices](https://cloud.google.com/architecture/rate-limiting-strategies-techniques)
- [Benchmarking Methodology RFC 2544](https://www.rfc-editor.org/rfc/rfc2544)
