"""Agent registry for managing agent-deployment pair registrations.

Provides lookup and listing of registered agents by name and deployment type.
"""

from benchmark.agents.base import AgentAdapter
from benchmark.models.domain import DeploymentType


class AgentRegistry:
    """Registry of available agent-deployment pairs.

    Req 3.4: Registered pairs are retrievable by agent name and deployment_type.
    Req 3.5: Returns None for unregistered pairs without raising.
    Req 3.6: Returns list of all pairs as (name, DeploymentType) tuples.
    Req 3.8: Duplicate registration replaces existing.
    """

    def __init__(self) -> None:
        self._agents: dict[tuple[str, DeploymentType], AgentAdapter] = {}
        self._endpoints: dict[tuple[str, DeploymentType], str] = {}

    def register(
        self,
        agent: AgentAdapter,
        deployment_type: DeploymentType,
        endpoint: str,
    ) -> None:
        """Register an agent-deployment pair with its endpoint.

        Req 3.4: Makes the pair retrievable by name and deployment_type.
        Req 3.8: Replaces existing registration if the same pair is registered again.
        """
        key = (agent.name, deployment_type)
        self._agents[key] = agent
        self._endpoints[key] = endpoint

    def get(self, agent_name: str, deployment_type: DeploymentType) -> AgentAdapter | None:
        """Retrieve an agent by name and deployment type.

        Req 3.5: Returns None if the pair has not been registered, without raising.
        """
        return self._agents.get((agent_name, deployment_type))

    def get_endpoint(self, agent_name: str, deployment_type: DeploymentType) -> str | None:
        """Retrieve the endpoint for a registered agent-deployment pair."""
        return self._endpoints.get((agent_name, deployment_type))

    def list_available(self) -> list[tuple[str, DeploymentType]]:
        """List all registered agent-deployment pairs.

        Req 3.6: Returns (name, DeploymentType) tuples. Empty list if none registered.
        """
        return list(self._agents.keys())
