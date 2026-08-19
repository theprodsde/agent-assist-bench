"""Agent adapter protocol and request/response models.

Defines the uniform interface all AI agents must implement (ADR-0007),
along with the AgentRequest and AgentResponse data models.
"""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from benchmark.models.domain import Attachment, InputType, LLMMetrics


class UnsupportedModalityError(BaseModel):
    """Stable, serializable error contract for unsupported input modalities.

    AgentResponse.errors remains a list of strings for compatibility with
    ExecutionResult and SQLite persistence. ``as_error`` provides the compact
    canonical representation adapters should place in that list.
    """

    code: Literal["unsupported_modality"] = "unsupported_modality"
    modality: InputType

    def as_error(self) -> str:
        """Return the stable string representation stored in error lists."""
        return f"{self.code}:{self.modality.value}"

    def __str__(self) -> str:
        """Render the persistence-compatible error representation."""
        return self.as_error()


class AgentRequest(BaseModel):
    """Request payload sent to an agent adapter.

    Req 3.1: Contains prompt (non-empty, max 100k), optional attachments,
    and optional conversation_id.
    """

    prompt: str
    attachments: list[Attachment] = Field(default_factory=list)
    conversation_id: str | None = None

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        """Prompt must be non-empty and at most 100,000 characters."""
        if not v:
            raise ValueError("Prompt must not be empty")
        if len(v) > 100_000:
            raise ValueError("Prompt must not exceed 100,000 characters")
        return v


class AgentResponse(BaseModel):
    """Response payload returned by an agent adapter.

    Req 3.1: Contains response content, optional LLM metrics, and errors list.
    Req 3.7: On failure, content is empty and errors list has at least one entry.
    """

    content: str = ""
    llm_metrics: LLMMetrics | None = None
    errors: list[str] = Field(default_factory=list)


@runtime_checkable
class AgentAdapter(Protocol):
    """Common interface for all AI agents (ADR-0007).

    Req 3.1: async execute(request) -> response
    Req 3.2: async health_check() -> bool (True if responds within 10s)
    Req 3.3: name and version read-only properties (non-empty, max 128 chars)
    """

    @property
    def name(self) -> str:
        """Agent name (non-empty, max 128 characters)."""
        ...

    @property
    def version(self) -> str:
        """Agent version (non-empty, max 128 characters)."""
        ...

    async def execute(self, request: AgentRequest) -> AgentResponse:
        """Execute a request and return response with metrics."""
        ...

    async def health_check(self) -> bool:
        """Check if the agent deployment is reachable (within 10s timeout)."""
        ...
