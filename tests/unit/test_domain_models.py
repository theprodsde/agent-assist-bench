"""Unit tests for domain models and validation rules."""

import time
from datetime import UTC

import pytest
from pydantic import ValidationError

from benchmark.models.domain import (
    VALID_SOURCES,
    Attachment,
    Benchmark,
    BenchmarkStatus,
    DeploymentMetrics,
    DeploymentType,
    Evaluation,
    Execution,
    ExecutionResult,
    ExportManifest,
    InputType,
    LLMMetrics,
)


class TestEnums:
    """Test enum definitions."""

    def test_benchmark_status_values(self):
        assert BenchmarkStatus.PENDING == "pending"
        assert BenchmarkStatus.RUNNING == "running"
        assert BenchmarkStatus.COMPLETED == "completed"
        assert BenchmarkStatus.PARTIALLY_FAILED == "partially_failed"
        assert BenchmarkStatus.FAILED == "failed"

    def test_input_type_values(self):
        assert InputType.TEXT == "text"
        assert InputType.IMAGE == "image"
        assert InputType.AUDIO == "audio"
        assert InputType.VIDEO == "video"
        assert InputType.DOCUMENT == "document"
        assert InputType.URL == "url"

    def test_deployment_type_values(self):
        assert DeploymentType.LOCAL_DOCKER == "local_docker"
        assert DeploymentType.VIRTUAL_MACHINE == "vm"
        assert DeploymentType.MANAGED_CONTAINER == "managed_container"


class TestULIDGeneration:
    """Test ULID generation for entity IDs (Req 10.1, 10.2, 10.3, 10.4)."""

    def test_benchmark_id_is_26_chars(self):
        b = Benchmark(source="cli", prompt="test")
        assert len(b.id) == 26

    def test_benchmark_id_crockford_base32(self):
        """Req 10.4: Only 0-9 and A-Z excluding I, L, O, U."""
        b = Benchmark(source="cli", prompt="test")
        valid_chars = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
        assert all(c in valid_chars for c in b.id.upper())

    def test_ulid_uniqueness(self):
        """Req 10.3: ULIDs within same millisecond are unique."""
        ids = {Benchmark(source="cli", prompt="test").id for _ in range(100)}
        assert len(ids) == 100

    def test_ulid_sortability(self):
        """Req 10.2: Earlier ULID < later ULID lexicographically."""
        b1 = Benchmark(source="cli", prompt="test")
        time.sleep(0.002)  # 2ms to ensure different timestamp
        b2 = Benchmark(source="cli", prompt="test")
        assert b1.id < b2.id

    def test_execution_id_is_ulid(self):
        from datetime import datetime

        e = Execution(
            benchmark_id="test",
            agent_name="hermes",
            agent_version="1.0",
            deployment=DeploymentMetrics(
                provider="local",
                deployment_type=DeploymentType.LOCAL_DOCKER,
                total_latency_ms=100.0,
            ),
            result=ExecutionResult(raw_response="response"),
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            success=True,
        )
        assert len(e.id) == 26

    def test_evaluation_id_is_ulid(self):
        e = Evaluation(benchmark_id="test", rating=3)
        assert len(e.id) == 26


class TestBenchmarkValidation:
    """Test Benchmark model validation rules."""

    def test_valid_benchmark(self):
        b = Benchmark(source="cli", prompt="Hello world")
        assert b.status == BenchmarkStatus.PENDING
        assert b.attachments == []
        assert b.execution_count == 0

    def test_empty_prompt_rejected(self):
        """Req 1.3: Reject empty prompt."""
        with pytest.raises(ValidationError, match="Prompt must not be empty"):
            Benchmark(source="cli", prompt="")

    def test_prompt_over_100k_rejected(self):
        """Req 1.3: Reject > 100,000 chars."""
        with pytest.raises(ValidationError, match="100,000 characters"):
            Benchmark(source="cli", prompt="x" * 100_001)

    def test_prompt_exactly_100k_accepted(self):
        b = Benchmark(source="cli", prompt="x" * 100_000)
        assert len(b.prompt) == 100_000

    def test_valid_sources_accepted(self):
        """Req 1.5: Source values: telegram, discord, cli, api."""
        for src in VALID_SOURCES:
            b = Benchmark(source=src, prompt="test")
            assert b.source == src

    def test_invalid_source_rejected(self):
        """Req 1.4: Invalid source rejected."""
        with pytest.raises(ValidationError, match="Source must be one of"):
            Benchmark(source="invalid", prompt="test")

    def test_max_10_attachments_accepted(self):
        """Req 1.1: At most 10 attachments."""
        attachments = [Attachment(type="text", content_base64="abc") for _ in range(10)]
        b = Benchmark(source="cli", prompt="test", attachments=attachments)
        assert len(b.attachments) == 10

    def test_over_10_attachments_rejected(self):
        """Req 1.1: More than 10 attachments rejected."""
        attachments = [Attachment(type="text", content_base64="abc") for _ in range(11)]
        with pytest.raises(ValidationError, match="at most 10"):
            Benchmark(source="cli", prompt="test", attachments=attachments)

    def test_default_status_is_pending(self):
        """Req 1.1: Status PENDING by default."""
        b = Benchmark(source="cli", prompt="test")
        assert b.status == BenchmarkStatus.PENDING


class TestAttachmentValidation:
    """Test Attachment model validation rules (Req 13)."""

    def test_image_requires_image_mime(self):
        """Req 13.2: IMAGE requires mime_type starting with image/."""
        with pytest.raises(ValidationError, match="image/"):
            Attachment(type="image", mime_type="text/plain", content_base64="abc")

    def test_image_with_valid_mime(self):
        a = Attachment(type="image", mime_type="image/png", content_base64="abc")
        assert a.type == InputType.IMAGE

    def test_audio_requires_audio_mime(self):
        """Req 13.3: AUDIO requires mime_type starting with audio/."""
        with pytest.raises(ValidationError, match="audio/"):
            Attachment(type="audio", mime_type="image/png", content_base64="abc")

    def test_audio_with_valid_mime(self):
        a = Attachment(type="audio", mime_type="audio/mp3", content_base64="abc")
        assert a.type == InputType.AUDIO

    def test_video_requires_video_mime(self):
        """Req 13.2/13.3: VIDEO requires mime_type starting with video/."""
        with pytest.raises(ValidationError, match="video/"):
            Attachment(type="video", mime_type="audio/mp4", content_base64="abc")

    def test_video_with_valid_mime_and_bytes(self):
        a = Attachment(
            type="video",
            filename="clip.mp4",
            mime_type="video/mp4",
            size_bytes=4,
            content_bytes=b"MP4!",
        )
        assert a.type == InputType.VIDEO
        assert a.content_bytes == b"MP4!"
        assert a.size_bytes == 4

    def test_document_requires_application_or_text_mime(self):
        """Req 13.7: DOCUMENT requires mime starting with application/ or text/."""
        with pytest.raises(ValidationError, match="application/"):
            Attachment(type="document", mime_type="image/png", content_base64="abc")

    def test_document_with_application_mime(self):
        a = Attachment(type="document", mime_type="application/pdf", content_base64="abc")
        assert a.type == InputType.DOCUMENT

    def test_document_with_text_mime(self):
        a = Attachment(type="document", mime_type="text/plain", content_base64="abc")
        assert a.type == InputType.DOCUMENT

    def test_url_requires_http_url(self):
        """Req 13.4: URL type requires url field with http:// or https://."""
        with pytest.raises(ValidationError, match="http://"):
            Attachment(type="url", url="ftp://example.com")

    def test_url_without_url_field_rejected(self):
        with pytest.raises(ValidationError):
            Attachment(type="url")

    def test_url_with_https(self):
        a = Attachment(type="url", url="https://example.com")
        assert a.type == InputType.URL

    def test_url_with_http(self):
        a = Attachment(type="url", url="http://example.com")
        assert a.type == InputType.URL

    def test_text_requires_exactly_one_content_source(self):
        """Req 13.5: TEXT requires exactly one of content_base64 or url."""
        # Both provided
        with pytest.raises(ValidationError, match="exactly one"):
            Attachment(type="text", content_base64="abc", url="https://example.com")
        # Neither provided
        with pytest.raises(ValidationError, match="exactly one"):
            Attachment(type="text")

    def test_text_with_content_base64(self):
        a = Attachment(type="text", content_base64="abc")
        assert a.content_base64 == "abc"

    def test_text_with_url(self):
        a = Attachment(type="text", url="https://example.com/file.txt")
        assert a.url == "https://example.com/file.txt"

    def test_image_requires_exactly_one_content_source(self):
        """Req 13.5: IMAGE requires exactly one of content_base64 or url."""
        with pytest.raises(ValidationError, match="exactly one"):
            Attachment(
                type="image",
                mime_type="image/png",
                content_base64="abc",
                url="https://example.com/img.png",
            )

    def test_audio_requires_exactly_one_content_source(self):
        """Req 13.5: AUDIO requires exactly one of content_base64 or url."""
        with pytest.raises(ValidationError, match="exactly one"):
            Attachment(type="audio", mime_type="audio/mp3")

    def test_document_requires_exactly_one_content_source(self):
        """Req 13.5: DOCUMENT requires exactly one of content_base64 or url."""
        with pytest.raises(ValidationError, match="exactly one"):
            Attachment(type="document", mime_type="application/pdf")


class TestEvaluationValidation:
    """Test Evaluation model validation rules (Req 6)."""

    def test_rating_below_1_rejected(self):
        with pytest.raises(ValidationError):
            Evaluation(benchmark_id="test", rating=0)

    def test_rating_above_5_rejected(self):
        with pytest.raises(ValidationError):
            Evaluation(benchmark_id="test", rating=6)

    def test_valid_ratings(self):
        for r in range(1, 6):
            e = Evaluation(benchmark_id="test", rating=r)
            assert e.rating == r

    def test_notes_over_10k_rejected(self):
        """Req 6: Notes max 10,000 characters."""
        with pytest.raises(ValidationError, match="10,000 characters"):
            Evaluation(benchmark_id="test", rating=3, notes="x" * 10_001)

    def test_notes_exactly_10k_accepted(self):
        e = Evaluation(benchmark_id="test", rating=3, notes="x" * 10_000)
        assert len(e.notes) == 10_000

    def test_optional_fields(self):
        e = Evaluation(benchmark_id="test", rating=3)
        assert e.preferred_agent is None
        assert e.preferred_deployment is None
        assert e.notes is None
        assert e.evaluator is None

    def test_preferred_deployment_is_deployment_type(self):
        e = Evaluation(
            benchmark_id="test",
            rating=4,
            preferred_deployment=DeploymentType.LOCAL_DOCKER,
        )
        assert e.preferred_deployment == DeploymentType.LOCAL_DOCKER


class TestDeploymentMetrics:
    """Test DeploymentMetrics validation."""

    def test_total_latency_must_be_positive(self):
        with pytest.raises(ValidationError, match="greater than zero"):
            DeploymentMetrics(
                provider="local",
                deployment_type=DeploymentType.LOCAL_DOCKER,
                total_latency_ms=0,
            )

    def test_total_latency_negative_rejected(self):
        with pytest.raises(ValidationError, match="greater than zero"):
            DeploymentMetrics(
                provider="local",
                deployment_type=DeploymentType.LOCAL_DOCKER,
                total_latency_ms=-1.0,
            )

    def test_valid_deployment_metrics(self):
        d = DeploymentMetrics(
            provider="aws",
            deployment_type=DeploymentType.MANAGED_CONTAINER,
            total_latency_ms=150.5,
            cold_start_ms=50.0,
        )
        assert d.total_latency_ms == 150.5


class TestLLMMetrics:
    """Test LLMMetrics model."""

    def test_all_optional_fields(self):
        m = LLMMetrics(model="gpt-4")
        assert m.prompt_tokens is None
        assert m.completion_tokens is None
        assert m.estimated_cost_usd is None

    def test_full_metrics(self):
        m = LLMMetrics(
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            api_latency_ms=500.0,
            estimated_cost_usd=0.05,
        )
        assert m.total_tokens == 300


class TestExportManifest:
    """Test ExportManifest model."""

    def test_valid_manifest(self):
        from datetime import datetime

        m = ExportManifest(
            date="2024-01-15",
            exported_at=datetime.now(UTC),
            files=["benchmarks_2024-01-15.csv", "executions_2024-01-15.csv"],
            benchmark_count=10,
            execution_count=30,
            evaluation_count=5,
        )
        assert m.benchmark_count == 10


class TestModelSerialization:
    """Test Pydantic model serialization round-trips."""

    def test_benchmark_json_roundtrip(self):
        b = Benchmark(source="cli", prompt="test", tags=["coding", "debug"])
        data = b.model_dump()
        b2 = Benchmark(**data)
        assert b2.id == b.id
        assert b2.source == b.source
        assert b2.prompt == b.prompt
        assert b2.tags == ["coding", "debug"]

    def test_attachment_json_roundtrip(self):
        a = Attachment(
            type="video",
            filename="clip.mp4",
            mime_type="video/mp4",
            size_bytes=4,
            content_bytes=b"MP4!",
        )
        data = a.model_dump()
        a2 = Attachment(**data)
        assert a2.type == InputType.VIDEO
        assert a2.filename == "clip.mp4"
        assert a2.mime_type == "video/mp4"
        assert a2.size_bytes == 4
        assert a2.content_bytes == b"MP4!"

    def test_evaluation_json_roundtrip(self):
        e = Evaluation(
            benchmark_id="test123",
            rating=4,
            preferred_agent="hermes",
            notes="Good response",
        )
        data = e.model_dump()
        e2 = Evaluation(**data)
        assert e2.rating == 4
        assert e2.preferred_agent == "hermes"
