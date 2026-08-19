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

The codebase has 266 unit tests. Help us add more:

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

To add support for a new agent framework:

### 1. Create an adapter in `benchmark/agents/`

```python
# benchmark/agents/myagent.py
from benchmark.agents.openai_compatible import OpenAICompatibleAdapter

class MyAgentAdapter(OpenAICompatibleAdapter):
    @property
    def name(self) -> str:
        return "MyAgent"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    # Override defaults if needed
    async def health_check(self) -> bool:
        # Custom health check logic
        return await super().health_check()
```

### 2. Register in `benchmark/agents/registry.py`

```python
from benchmark.agents.myagent import MyAgentAdapter

ADAPTERS = {
    "myagent": MyAgentAdapter,
    # ...
}
```

### 3. Add tests in `tests/unit/agents/test_myagent.py`

```python
import pytest
from benchmark.agents.myagent import MyAgentAdapter

def test_myagent_adapter():
    adapter = MyAgentAdapter(endpoint="http://localhost:9000", api_key="test")
    assert adapter.name == "MyAgent"
    assert adapter.version == "1.0.0"
```

### 4. Update documentation

- Add to [CLI.md](CLI.md)
- Update [DEPLOYMENT.md](DEPLOYMENT.md) if it requires special setup
- Update [README.md](README.md) status table

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
