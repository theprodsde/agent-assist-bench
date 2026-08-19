# 11 — Agent Interface

*Status: To be detailed in Phase 0*

## Overview

Every agent implements the `AgentAdapter` protocol. See [ADR-0007](ADR/ADR-0007-agent-abstraction.md).

## Interface

```python
class AgentAdapter(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def version(self) -> str: ...
    async def execute(self, request: AgentRequest) -> AgentResponse: ...
    async def health_check(self) -> bool: ...
```

## Initial Agents

- Hermes
- OpenClaw

## Future Agents

- Letta
- Agent Zero
- Open Interpreter
- Commercial agents (optional)

See the [design spec](../.kiro/specs/agent-assist-bench/design.md) for complete interface definitions and adapter implementations.

---

→ Previous: [10 — Benchmark Methodology](10-benchmark-methodology.md)  
→ Next: [12 — Deployment Design](12-deployment-design.md)
