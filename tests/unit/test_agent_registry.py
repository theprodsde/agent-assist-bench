"""Unit tests for AgentAdapter protocol and AgentRegistry.

Tests cover:
- Register and retrieve agent-deployment pairs (Req 3.4)
- Return None for unregistered pairs (Req 3.5)
- List all registered pairs (Req 3.6)
- Duplicate registration replaces existing (Req 3.8)
- AgentRequest/AgentResponse validation (Req 3.1, 3.3)
"""

import pytest

from benchmark.agents.base import (
    AgentAdapter,
    AgentRequest,
    AgentResponse,
    UnsupportedModalityError,
)
from benchmark.agents.registry import AgentRegistry
from benchmark.models.domain import DeploymentType, ExecutionResult, InputType

# --- Fake agent for testing ---


class FakeAgent:
    """A minimal AgentAdapter implementation for testing."""

    def __init__(self, name: str = "fake-agent", version: str = "1.0.0") -> None:
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    async def execute(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(content=f"Response to: {request.prompt}")

    async def health_check(self) -> bool:
        return True


# --- Protocol conformance ---


class TestAgentAdapterProtocol:
    """Test that FakeAgent satisfies the AgentAdapter protocol."""

    def test_fake_agent_is_agent_adapter(self) -> None:
        agent = FakeAgent()
        assert isinstance(agent, AgentAdapter)

    def test_name_and_version_properties(self) -> None:
        agent = FakeAgent(name="test-agent", version="2.1.0")
        assert agent.name == "test-agent"
        assert agent.version == "2.1.0"


# --- AgentRequest validation ---


class TestAgentRequest:
    """Test AgentRequest model validation (Req 3.1)."""

    def test_valid_request(self) -> None:
        req = AgentRequest(prompt="Hello, agent!")
        assert req.prompt == "Hello, agent!"
        assert req.attachments == []
        assert req.conversation_id is None

    def test_request_with_legacy_attachment(self) -> None:
        attachments = [
            {
                "type": "image",
                "filename": "diagram.png",
                "mime_type": "image/png",
                "size_bytes": 3,
                "content_bytes": b"PNG",
            },
            {
                "type": "audio",
                "filename": "note.mp3",
                "mime_type": "audio/mpeg",
                "size_bytes": 4,
                "content_base64": "bXAz",
            },
            {
                "type": "video",
                "filename": "clip.mp4",
                "mime_type": "video/mp4",
                "size_bytes": 42,
                "url": "https://cdn.example/clip.mp4",
            },
        ]

        request = AgentRequest(prompt="Review these files", attachments=attachments)
        restored = AgentRequest(**request.model_dump())

        assert [a.model_dump() for a in restored.attachments] == [
            a.model_dump() for a in request.attachments
        ]
        assert restored.attachments[0].content_bytes == b"PNG"
        assert restored.attachments[2].url == "https://cdn.example/clip.mp4"

    def test_unsupported_modality_error_is_stable_and_persistable(self) -> None:
        error = UnsupportedModalityError(modality=InputType.VIDEO)

        assert error.code == "unsupported_modality"
        assert error.modality == InputType.VIDEO
        assert error.as_error() == "unsupported_modality:video"
        assert str(error) == error.as_error()

        response = AgentResponse(content="partial response", errors=[error.as_error()])
        assert response.content == "partial response"
        assert response.errors == ["unsupported_modality:video"]

        result = ExecutionResult(raw_response=response.content, errors=response.errors)
        assert result.errors == ["unsupported_modality:video"]

    def test_prompt_exceeding_max_length_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not exceed 100,000"):
            AgentRequest(prompt="x" * 100_001)

    def test_prompt_at_max_length_accepted(self) -> None:
        req = AgentRequest(prompt="x" * 100_000)
        assert len(req.prompt) == 100_000


# --- AgentResponse ---


class TestAgentResponse:
    """Test AgentResponse model (Req 3.1, 3.7)."""

    def test_default_response(self) -> None:
        resp = AgentResponse()
        assert resp.content == ""
        assert resp.llm_metrics is None
        assert resp.errors == []

    def test_response_with_content(self) -> None:
        resp = AgentResponse(content="Here's the answer")
        assert resp.content == "Here's the answer"

    def test_error_response(self) -> None:
        resp = AgentResponse(content="", errors=["Connection timed out"])
        assert resp.content == ""
        assert len(resp.errors) == 1
        assert "Connection timed out" in resp.errors[0]


# --- AgentRegistry ---


class TestAgentRegistry:
    """Test AgentRegistry operations (Req 3.4, 3.5, 3.6, 3.8)."""

    def setup_method(self) -> None:
        self.registry = AgentRegistry()
        self.agent = FakeAgent(name="hermes", version="1.0.0")

    def test_register_and_get(self) -> None:
        """Req 3.4: Registered pairs are retrievable by name and deployment_type."""
        self.registry.register(self.agent, DeploymentType.LOCAL_DOCKER, "http://localhost:8080")
        result = self.registry.get("hermes", DeploymentType.LOCAL_DOCKER)
        assert result is not None
        assert result.name == "hermes"
        assert result.version == "1.0.0"

    def test_get_unregistered_returns_none(self) -> None:
        """Req 3.5: Returns None for unregistered pairs without raising."""
        result = self.registry.get("nonexistent", DeploymentType.VIRTUAL_MACHINE)
        assert result is None

    def test_get_wrong_deployment_type_returns_none(self) -> None:
        """Req 3.5: Same agent name but different deployment type returns None."""
        self.registry.register(self.agent, DeploymentType.LOCAL_DOCKER, "http://localhost:8080")
        result = self.registry.get("hermes", DeploymentType.VIRTUAL_MACHINE)
        assert result is None

    def test_list_available_empty(self) -> None:
        """Req 3.6: Empty list if no pairs registered."""
        assert self.registry.list_available() == []

    def test_list_available_with_registrations(self) -> None:
        """Req 3.6: Returns all registered (name, DeploymentType) tuples."""
        agent2 = FakeAgent(name="openclaw", version="2.0.0")
        self.registry.register(self.agent, DeploymentType.LOCAL_DOCKER, "http://localhost:8080")
        self.registry.register(agent2, DeploymentType.VIRTUAL_MACHINE, "http://vm:9090")
        available = self.registry.list_available()
        assert len(available) == 2
        assert ("hermes", DeploymentType.LOCAL_DOCKER) in available
        assert ("openclaw", DeploymentType.VIRTUAL_MACHINE) in available

    def test_duplicate_registration_replaces(self) -> None:
        """Req 3.8: Duplicate registration replaces existing."""
        self.registry.register(self.agent, DeploymentType.LOCAL_DOCKER, "http://localhost:8080")
        # Register a new agent with the same name and deployment type
        new_agent = FakeAgent(name="hermes", version="2.0.0")
        self.registry.register(new_agent, DeploymentType.LOCAL_DOCKER, "http://localhost:9090")
        result = self.registry.get("hermes", DeploymentType.LOCAL_DOCKER)
        assert result is not None
        assert result.version == "2.0.0"
        # Only one entry in the list
        assert len(self.registry.list_available()) == 1

    def test_duplicate_replaces_endpoint(self) -> None:
        """Req 3.8: Endpoint is also replaced on duplicate registration."""
        self.registry.register(self.agent, DeploymentType.LOCAL_DOCKER, "http://localhost:8080")
        new_agent = FakeAgent(name="hermes", version="2.0.0")
        self.registry.register(new_agent, DeploymentType.LOCAL_DOCKER, "http://localhost:9090")
        endpoint = self.registry.get_endpoint("hermes", DeploymentType.LOCAL_DOCKER)
        assert endpoint == "http://localhost:9090"

    def test_multiple_deployments_same_agent(self) -> None:
        """Same agent can be registered under multiple deployment types."""
        self.registry.register(self.agent, DeploymentType.LOCAL_DOCKER, "http://localhost:8080")
        self.registry.register(self.agent, DeploymentType.VIRTUAL_MACHINE, "http://vm:8080")
        assert self.registry.get("hermes", DeploymentType.LOCAL_DOCKER) is not None
        assert self.registry.get("hermes", DeploymentType.VIRTUAL_MACHINE) is not None
        assert len(self.registry.list_available()) == 2

    def test_get_endpoint_unregistered_returns_none(self) -> None:
        """get_endpoint returns None for unregistered pair."""
        assert self.registry.get_endpoint("nope", DeploymentType.LOCAL_DOCKER) is None
