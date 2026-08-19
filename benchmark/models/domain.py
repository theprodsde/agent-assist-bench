"""Core domain models and enums for AgentAssistBench."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ulid import ULID

# --- Enums ---


class BenchmarkStatus(StrEnum):
    """Status of a benchmark execution lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class InputType(StrEnum):
    """Type of attachment input."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    URL = "url"


class DeploymentType(StrEnum):
    """Infrastructure deployment configuration."""

    LOCAL_DOCKER = "local_docker"
    VIRTUAL_MACHINE = "vm"
    MANAGED_CONTAINER = "managed_container"


# --- Valid source values ---

VALID_SOURCES = ("telegram", "discord", "cli", "api")


# --- Helper for ULID generation ---


def _generate_ulid() -> str:
    """Generate a new ULID string."""
    return str(ULID())


# --- Domain Models ---


class Attachment(BaseModel):
    """A file or URL attached to a benchmark or agent request.

    ``content_bytes`` is the in-memory representation used by adapters while
    ``content_base64`` remains the portable representation used by API and
    storage boundaries.  Extra fields are retained for compatibility with
    older connector payloads rather than being silently discarded.
    """

    model_config = ConfigDict(extra="allow")

    type: InputType
    filename: str | None = None
    url: str | None = None
    content_base64: str | None = None
    content_bytes: bytes | None = None
    mime_type: str | None = None
    size_bytes: int | None = None

    @model_validator(mode="after")
    def validate_type_consistency(self) -> "Attachment":
        """Validate modality MIME type and exactly one content source."""
        mime_prefixes = {
            InputType.IMAGE: "image/",
            InputType.AUDIO: "audio/",
            InputType.VIDEO: "video/",
        }
        required_prefix = mime_prefixes.get(self.type)
        if required_prefix and (
            not self.mime_type or not self.mime_type.startswith(required_prefix)
        ):
            raise ValueError(
                f"Attachment type {self.type.name} requires mime_type starting with "
                f"'{required_prefix}'"
            )

        if self.type == InputType.DOCUMENT and (
            not self.mime_type
            or not (self.mime_type.startswith("application/") or self.mime_type.startswith("text/"))
        ):
            raise ValueError(
                "Attachment type DOCUMENT requires mime_type starting with "
                "'application/' or 'text/'"
            )

        if self.type == InputType.URL:
            if not self.url or not self.url.startswith(("http://", "https://")):
                raise ValueError(
                    "Attachment type URL requires url field starting with 'http://' or 'https://'"
                )
            return self

        # ``content`` was accepted by the original untyped AgentRequest. Keep
        # it as a valid legacy source when supplied as an extra field.
        has_legacy_content = bool(self.model_extra and self.model_extra.get("content") is not None)
        content_sources = (
            self.content_base64 is not None,
            self.content_bytes is not None,
            has_legacy_content,
            self.url is not None,
        )
        if sum(content_sources) != 1:
            raise ValueError(
                f"Attachment type {self.type.value} requires exactly one of "
                "content_base64, content_bytes, or url"
            )

        return self


class Benchmark(BaseModel):
    """A single benchmark request with all metadata."""

    id: str = Field(default_factory=_generate_ulid)
    conversation_id: str | None = None
    source: str
    prompt: str
    attachments: list[Attachment] = Field(default_factory=list)
    status: BenchmarkStatus = BenchmarkStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    execution_count: int = 0
    tags: list[str] = Field(default_factory=list)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        """Req 1.3: Reject empty prompt or > 100,000 chars."""
        if not v or len(v) == 0:
            raise ValueError("Prompt must not be empty")
        if len(v) > 100_000:
            raise ValueError("Prompt must not exceed 100,000 characters")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Req 1.4/1.5: Source must be one of telegram, discord, cli, api."""
        if v not in VALID_SOURCES:
            raise ValueError(f"Source must be one of: {', '.join(VALID_SOURCES)}. Got: '{v}'")
        return v

    @field_validator("attachments")
    @classmethod
    def validate_attachments_count(cls, v: list[Attachment]) -> list[Attachment]:
        """Req 1.1: Max 10 attachments."""
        if len(v) > 10:
            raise ValueError("Benchmark may have at most 10 attachments")
        return v


class DeploymentMetrics(BaseModel):
    """Infrastructure metrics for a single execution."""

    provider: str
    deployment_type: DeploymentType
    cpu_cores: float | None = None
    memory_mb: int | None = None
    cold_start_ms: float | None = None
    total_latency_ms: float
    network_latency_ms: float | None = None
    estimated_infra_cost_usd: float | None = None

    @field_validator("total_latency_ms")
    @classmethod
    def validate_total_latency(cls, v: float) -> float:
        """Total latency must be positive."""
        if v <= 0:
            raise ValueError("total_latency_ms must be greater than zero")
        return v


class LLMMetrics(BaseModel):
    """LLM-specific metrics for a single execution."""

    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    api_latency_ms: float | None = None
    estimated_cost_usd: float | None = None


class ExecutionResult(BaseModel):
    """Raw result from a single agent execution."""

    raw_response: str
    tool_calls: list[dict] | None = None
    browser_actions: list[dict] | None = None
    errors: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


class Execution(BaseModel):
    """A single agent-deployment execution within a benchmark."""

    id: str = Field(default_factory=_generate_ulid)
    benchmark_id: str
    agent_name: str
    agent_version: str
    deployment: DeploymentMetrics
    llm: LLMMetrics | None = None
    result: ExecutionResult
    started_at: datetime
    completed_at: datetime
    success: bool


class Evaluation(BaseModel):
    """Human evaluation of a benchmark's results."""

    id: str = Field(default_factory=_generate_ulid)
    benchmark_id: str
    rating: int = Field(ge=1, le=5)
    preferred_agent: str | None = None
    preferred_deployment: DeploymentType | None = None
    notes: str | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluator: str | None = None

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        """Req 6: Notes max 10,000 characters."""
        if v is not None and len(v) > 10_000:
            raise ValueError("Notes must not exceed 10,000 characters")
        return v


class ExportManifest(BaseModel):
    """Manifest for a daily export run."""

    date: str
    exported_at: datetime
    files: list[str]
    benchmark_count: int
    execution_count: int
    evaluation_count: int
