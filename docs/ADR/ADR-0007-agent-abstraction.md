# ADR-0007: Agent Abstraction

**Status:** Accepted  
**Date:** 2026-07-30

## Context

AgentAssistBench must support multiple AI agents that have fundamentally different:

- API formats (REST, WebSocket, gRPC)
- Authentication mechanisms (API keys, OAuth, none)
- Response formats (plain text, structured JSON, streaming)
- Capabilities (text-only, multimodal, browser automation, tool use)
- Deployment requirements (specific ports, environment variables, GPU)

The benchmark runner should not know or care about these differences. It needs a uniform way to send a prompt and receive a response with timing metrics.

## Decision

Every agent implements a common interface. The benchmark runner interacts only with this interface.

### Agent Protocol

```python
@runtime_checkable
class AgentAdapter(Protocol):
    """Common interface for all AI agents."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute a request and return response with metrics."""
        ...

    async def health_check(self) -> bool:
        """Check if the agent deployment is reachable."""
        ...
```

### Agent Registry

```python
class AgentRegistry:
    """Registry of available agent-deployment pairs."""

    def register(self, agent: AgentAdapter, deployment_type: DeploymentType, endpoint: str) -> None: ...
    def get(self, agent_name: str, deployment_type: DeploymentType) -> AgentAdapter | None: ...
    def list_available(self) -> list[tuple[str, DeploymentType]]: ...
```

### Initial Agents

| Agent | Type | Status |
|-------|------|--------|
| Hermes | Open-source AI assistant | v1 |
| OpenClaw | Open-source AI assistant | v1 |
| Letta | Memory-augmented agent | Future |
| Open Interpreter | Code execution agent | Future |
| Commercial agents | Various | Optional adapters |

### Adapter Responsibilities

Each adapter handles:

1. Translating `AgentRequest` to the agent's native API format
2. Parsing the agent's native response into `AgentResponse`
3. Extracting LLM metrics (tokens, model, cost) from the response
4. Managing agent-specific authentication
5. Timeout and error handling

## Consequences

### Positive

- Adding a new agent requires only implementing the adapter interface
- Benchmark runner is completely decoupled from agent internals
- Easy to test (mock adapters for unit tests)
- Agents can be swapped without changing any other component
- Future agents can be contributed by the community

### Negative

- Some agent-specific features cannot be captured through the common interface
- Adapters may need to make multiple API calls to fulfill one `execute()` call
- Version reporting depends on agents exposing version information
- Health check semantics vary across agents

### Mitigations

- `AgentResponse` includes flexible fields (tool_calls, browser_actions) for agent-specific data
- Adapter implementations can make multiple internal calls transparently
- Version can default to "unknown" if agent doesn't report it
- Health check is best-effort (HTTP 200 from any endpoint)

## Alternatives Considered

1. **Direct API calls without abstraction** — Rejected because it couples the runner to specific agents and makes adding new agents require runner changes
2. **Message queue between runner and agents** — Rejected because it adds infrastructure complexity (RabbitMQ/Kafka) without benefit for single-user synchronous benchmarks
3. **gRPC interface** — Rejected because most agents expose REST APIs; requiring gRPC would force adapter complexity on both sides
4. **OpenAI-compatible API standard** — Considered but rejected because not all agents follow OpenAI's format, and the benchmark measures more than just chat completions

## References

- [Python Protocol (PEP 544)](https://peps.python.org/pep-0544/) — Structural subtyping
- [Adapter Pattern](https://refactoring.guru/design-patterns/adapter)
- [Strategy Pattern](https://refactoring.guru/design-patterns/strategy)
