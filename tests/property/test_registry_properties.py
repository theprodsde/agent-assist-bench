"""Property tests for Agent Registry (Task 5.2).

Tests:
- Property 11: Agent Registry Round-Trip
- Duplicate registration replaces existing
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.agents.base import AgentRequest, AgentResponse
from benchmark.agents.registry import AgentRegistry
from benchmark.models.domain import DeploymentType


class MockAgentAdapter:
    """Simple mock implementing the AgentAdapter protocol."""

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(content="mock response")

    async def health_check(self) -> bool:
        return True


# --- Property 11: Agent Registry Round-Trip ---


@settings(max_examples=20)
@given(
    names=st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"), min_codepoint=65, max_codepoint=122
            ),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=5,
    ),
    deployment_types=st.lists(
        st.sampled_from(list(DeploymentType)),
        min_size=1,
        max_size=5,
    ),
)
def test_registry_round_trip(names: list[str], deployment_types: list[DeploymentType]) -> None:
    """Registered agent-deployment pairs are retrievable; unregistered return None."""
    registry = AgentRegistry()

    # Register combinations
    registered_pairs: list[tuple[str, DeploymentType]] = []
    for name in names:
        for dt in deployment_types:
            adapter = MockAgentAdapter(name=name)
            registry.register(adapter, dt, endpoint=f"http://{name}/{dt}")
            registered_pairs.append((name, dt))

    # Verify retrieval by exact key
    for name, dt in registered_pairs:
        result = registry.get(name, dt)
        assert result is not None
        assert result.name == name

    # Verify unregistered key returns None
    unknown_result = registry.get("__never_registered__", DeploymentType.LOCAL_DOCKER)
    assert unknown_result is None

    # Verify list_available returns all unique registered pairs
    available = registry.list_available()
    unique_pairs = set(registered_pairs)
    assert set(available) == unique_pairs


def test_duplicate_registration_replaces_existing() -> None:
    """Registering the same (name, deployment_type) pair replaces the adapter."""
    registry = AgentRegistry()

    adapter_v1 = MockAgentAdapter(name="agent-x", version="1.0.0")
    adapter_v2 = MockAgentAdapter(name="agent-x", version="2.0.0")

    registry.register(adapter_v1, DeploymentType.LOCAL_DOCKER, endpoint="http://v1")
    registry.register(adapter_v2, DeploymentType.LOCAL_DOCKER, endpoint="http://v2")

    retrieved = registry.get("agent-x", DeploymentType.LOCAL_DOCKER)
    assert retrieved is not None
    assert retrieved.version == "2.0.0"

    # Only one entry in the list
    available = registry.list_available()
    assert available.count(("agent-x", DeploymentType.LOCAL_DOCKER)) == 1
