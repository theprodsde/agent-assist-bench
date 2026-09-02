# Contributing to AgentAssistBench

Thank you for your interest in contributing! This guide will help you get started.

## Code of Conduct

Be respectful and inclusive. We're all here to make this better.

## Getting Started

### 1. Clone and install

```bash
git clone https://github.com/theprodsde/agent-assist-bench.git
cd agent-assist-bench
pip install -e ".[dev]"
```

### 2. Create a feature branch

```bash
git checkout -b feature/your-feature-name
```

### 3. Make your changes

Keep commits focused and write clear commit messages.

### 4. Run tests and lint

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/unit/test_runner.py -v

# Lint
ruff check benchmark/ tests/
ruff format benchmark/ tests/

# Type check
mypy benchmark/
```

### 5. Push and open a Pull Request

```bash
git push origin feature/your-feature-name
```

Open a PR against `main`. Describe what you changed and why.

---

## Contribution Areas

### 🐛 Bug Fixes

Found a bug? Check [Issues](https://github.com/theprodsde/agent-assist-bench/issues) first, then:

1. Open an issue describing the bug
2. Fork and fix it
3. Add a test case that would have caught it
4. Submit a PR

### ✨ Features

New features should align with the [roadmap](docs/16-roadmap.md). Check open [Issues](https://github.com/theprodsde/agent-assist-bench/issues) and [Discussions](https://github.com/theprodsde/agent-assist-bench/discussions) first.

For larger features:
1. Open a Discussion or GitHub Issue to propose the idea
2. Get feedback before coding
3. If approved, implement as described above

### 📚 Documentation

Documentation improvements are always welcome:

- Typo fixes
- Clarifying confusing sections
- Adding examples
- Improving diagrams

For large doc restructures, open an Issue first.

### 🧪 Tests

The codebase has 505 tests (unit, property-based, integration). Help us add more:

- Test new features you add
- Add regression tests for bugs you fix
- Improve test coverage

Run the test suite:

```bash
pytest tests/ -v
pytest tests/unit/ -v          # unit tests only
pytest tests/integration/ -v   # integration tests only
pytest tests/property/ -v      # property-based tests
```

---

## Code Style

### Python

- **3.11+**: All code must be compatible with Python 3.11+
- **Formatting**: Use `ruff format` (no manual formatting)
- **Linting**: Use `ruff check` — fix all errors
- **Type hints**: Required for all functions and classes (strict mode with `mypy`)
- **Line length**: 100 characters (configured in `pyproject.toml`)

### Commits

- Descriptive messages (not `fix typo` or `update`)
- Reference issues when relevant: `Fixes #123`
- One feature per commit when possible

### PRs

- Link related Issues
- Describe what changed and why
- Screenshot/output if applicable
- Keep PR scope focused

---

## Project Structure

```
benchmark/
├── agents/           # Agent adapters (OpenAI-compatible, Hermes, OpenClaw)
├── cli/              # CLI commands (run, status, evaluate, report)
├── config/           # Settings and environment loading
├── evaluation/       # Evaluation service and rules
├── models/           # Domain models (Benchmark, Execution, Evaluation)
├── report/           # Report generation
├── runner/           # Benchmark execution engine
├── storage/          # SQLite persistence
├── export/           # Daily export to JSONL/CSV
└── __init__.py

tests/
├── unit/             # Unit tests (no I/O, no database)
├── integration/      # Integration tests (may use real SQLite)
└── property/         # Property-based tests
```

---

## Adding a New Agent

There are two paths depending on how non-standard the framework is.

---

### Path A — Zero code (any standard OpenAI-compatible endpoint)

If the framework exposes `/v1/chat/completions` (Ollama, vLLM, LiteLLM, LibreChat,
Open WebUI, and most modern agent servers do), just add it to `.env`:

```env
BENCH_AGENTS_JSON=[{"name":"my-framework","endpoint":"http://localhost:PORT/v1","model":"model-name","api_key":"optional-key"}]
```

No code changes needed. Multiple agents:

```env
BENCH_AGENTS_JSON=[
  {"name":"ollama-llama3","endpoint":"http://localhost:11434/v1","model":"llama3"},
  {"name":"librechat","endpoint":"http://localhost:9000/v1","model":"gpt-4o","api_key":"sk-..."}
]
```

This is the right path for 95% of frameworks. Only use Path B if you need something
the OpenAI API contract can't express (custom auth scheme, non-standard response
format, framework-specific pre/post-processing, etc.).

---

### Path B — Custom adapter (~80 lines)

Use **composition**, not inheritance. The existing `HermesAdapter` and `OpenClawAdapter`
are the canonical examples — both delegate all HTTP work to `OpenAICompatibleAdapter`
via `self._inner` and simply provide agent-specific identity and logging context.

#### 1. Create `benchmark/agents/myagent.py`

```python
from __future__ import annotations
from typing import TYPE_CHECKING
import structlog
from benchmark.agents.openai_compatible import OpenAICompatibleAdapter

if TYPE_CHECKING:
    import httpx
    from benchmark.agents.base import AgentRequest, AgentResponse

logger = structlog.get_logger()

class MyAgentAdapter:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        signing_key: str | None = None,
        model: str = "my-default-model",
        timeout: float = 120.0,
        client: "httpx.AsyncClient | None" = None,
    ) -> None:
        self._inner = OpenAICompatibleAdapter(
            endpoint=endpoint,
            model=model,
            agent_name="myagent",
            agent_version="1.0.0",
            api_key=api_key,
            signing_key=signing_key,
            timeout=timeout,
            client=client,
        )
        self._log = logger.bind(agent_name="myagent")

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def version(self) -> str:
        return self._inner.version

    async def execute(self, request: "AgentRequest") -> "AgentResponse":
        return await self._inner.execute(request)

    async def health_check(self) -> bool:
        return await self._inner.health_check()

    async def close(self) -> None:
        await self._inner.close()
```

#### 2. Add settings in `benchmark/config/settings.py`

```python
myagent_endpoint: str = "http://localhost:9000"
myagent_api_key: SecretStr = SecretStr("")
myagent_deployment_type: str = "local_docker"
```

#### 3. Wire it in `benchmark/cli/wiring.py`

Add a block inside `_build_agent_specs()`, following the Hermes/OpenClaw pattern:

```python
from benchmark.agents.myagent import MyAgentAdapter

if myagent_key := settings.myagent_api_key.get_secret_value():
    specs.append(
        _AgentWireSpec(
            name="myagent",
            endpoint=settings.myagent_endpoint,
            deployment_type=_resolve_deployment_type(settings.myagent_deployment_type),
            factory=lambda: MyAgentAdapter(
                endpoint=settings.myagent_endpoint,
                api_key=myagent_key,
                signing_key=signing_key,
            ),
        )
    )
else:
    logger.warning("agent_skipped_missing_api_key", agent="myagent")
```

#### 4. Add tests in `tests/unit/test_myagent.py`

```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch
from benchmark.agents.myagent import MyAgentAdapter
from benchmark.agents.base import AgentRequest

def test_myagent_name_and_version():
    adapter = MyAgentAdapter(endpoint="http://localhost:9000/v1")
    assert adapter.name == "myagent"
    assert adapter.version == "1.0.0"

async def test_myagent_execute_delegates_to_inner(respx_mock):
    respx_mock.post("http://localhost:9000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hello"}}]
        })
    )
    adapter = MyAgentAdapter(endpoint="http://localhost:9000/v1")
    resp = await adapter.execute(AgentRequest(prompt="hi"))
    assert resp.content == "hello"
    assert not resp.errors
```

#### 5. Update `.env.example` and docs

- Add the new `BENCH_MYAGENT_*` vars to `.env.example`
- Update [README.md](README.md) Key Features if relevant

---

> **Opening a PR to add an adapter?**
> Use the [new agent issue template](.github/ISSUE_TEMPLATE/new_agent.yml) to track it,
> and link the issue in your PR description.

---

## Running Integration Tests

Integration tests create a real SQLite database. They're slower but necessary:

```bash
pytest tests/integration/ -v

# Run specific test
pytest tests/integration/test_storage.py::test_benchmark_crud -v

# With logging
pytest tests/integration/ -v -s  # -s shows print() output
```

---

## CI/CD

GitHub Actions runs on every PR:

- **Tests**: `pytest tests/ -v`
- **Lint**: `ruff check benchmark/ tests/`
- **Type check**: `mypy benchmark/`
- **Format check**: `ruff format --check benchmark/ tests/`

All checks must pass before merging.

To run locally before pushing:

```bash
ruff check . && ruff format --check . && mypy benchmark/ && pytest tests/ -v
```

---

## Documentation Contribution Workflow

### Updating existing docs

1. Edit the `.md` file directly
2. Run local markdown linter (optional): `markdownlint docs/**/*.md`
3. Submit PR

### Adding new docs

1. Create the file in [docs/](docs/)
2. Link from [docs/README.md](docs/README.md) table of contents
3. Follow the naming convention: `NN-name.md` for numbered docs, `RFC-*` for proposals
4. Submit PR

---

## Licensing

By submitting a contribution, you agree that it will be licensed under the same MIT license as the project.

---

## Questions?

- Join the [Discussions](https://github.com/theprodsde/agent-assist-bench/discussions)
- Open an [Issue](https://github.com/theprodsde/agent-assist-bench/issues) with a question tag
- Check existing [Issues](https://github.com/theprodsde/agent-assist-bench/issues) and PRs first

---

**Thank you for contributing!** 🙌
