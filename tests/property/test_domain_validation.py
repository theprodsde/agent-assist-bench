"""Property tests for domain model validation (Task 2.2).

Tests:
- Property 12: Invalid Prompts Rejected
- Property 13: Invalid Sources Rejected
- Property 14: Attachment Type-Mime Consistency
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from benchmark.models.domain import (
    VALID_SOURCES,
    Attachment,
    Benchmark,
    InputType,
)

# --- Property 12: Invalid Prompts Rejected ---


@settings(max_examples=20)
@given(
    extra_len=st.integers(min_value=1, max_value=10_000),
)
def test_overly_long_prompt_rejected(extra_len: int) -> None:
    """Prompts exceeding 100k characters must raise ValidationError."""
    prompt = "x" * (100_000 + extra_len)
    with pytest.raises(ValidationError):
        Benchmark(source="cli", prompt=prompt)


@settings(max_examples=20)
@given(prompt=st.just(""))
def test_empty_prompt_rejected(prompt: str) -> None:
    """Empty prompts must raise ValidationError."""
    with pytest.raises(ValidationError):
        Benchmark(source="cli", prompt=prompt)


# --- Property 13: Invalid Sources Rejected ---


@settings(max_examples=20)
@given(source=st.text(min_size=1, max_size=50).filter(lambda s: s not in VALID_SOURCES))
def test_invalid_source_rejected(source: str) -> None:
    """Sources not in VALID_SOURCES must raise ValidationError."""
    with pytest.raises(ValidationError):
        Benchmark(source=source, prompt="test prompt")


# --- Property 14: Attachment Type-Mime Consistency ---

# Map each media type to mime prefixes that are WRONG for it
_MISMATCHED_MIMES: dict[InputType, list[str]] = {
    InputType.IMAGE: ["audio/mp3", "video/mp4", "application/pdf"],
    InputType.AUDIO: ["image/png", "video/mp4", "application/json"],
    InputType.VIDEO: ["image/jpeg", "audio/wav", "text/plain"],
}


@settings(max_examples=20)
@given(
    type_key=st.sampled_from(list(_MISMATCHED_MIMES.keys())),
    data=st.data(),
)
def test_mismatched_type_mime_rejected(type_key: InputType, data: st.DataObject) -> None:
    """Attachment with type/mime_type mismatch must raise ValidationError."""
    bad_mime = data.draw(st.sampled_from(_MISMATCHED_MIMES[type_key]))
    with pytest.raises(ValidationError):
        Attachment(
            type=type_key,
            mime_type=bad_mime,
            content_base64="dGVzdA==",
        )


@settings(max_examples=20)
@given(
    type_key=st.sampled_from([InputType.IMAGE, InputType.AUDIO, InputType.VIDEO]),
)
def test_missing_mime_type_rejected(type_key: InputType) -> None:
    """Media attachments without mime_type must raise ValidationError."""
    with pytest.raises(ValidationError):
        Attachment(
            type=type_key,
            mime_type=None,
            content_base64="dGVzdA==",
        )
