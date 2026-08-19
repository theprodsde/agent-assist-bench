"""Property and unit tests for ULID generation and sortability (Task 2.3 + 11.3).

Tests:
- ULID format: 26-char Crockford base32
- Uniqueness: 100 ULIDs are all distinct
- Property 4: Sortability — sequential models have lexicographically ordered IDs
- Pydantic serialization round-trip
"""

import re
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.models.domain import VALID_SOURCES, Benchmark, BenchmarkStatus

# Crockford base32 alphabet (uppercase, no I/L/O/U)
_CROCKFORD_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_ulid_format() -> None:
    """Generated ULID must be 26-char Crockford base32."""
    b = Benchmark(source="cli", prompt="hello")
    assert len(b.id) == 26
    assert _CROCKFORD_PATTERN.match(b.id), f"ULID {b.id!r} does not match Crockford base32"


def test_ulid_uniqueness() -> None:
    """100 generated ULIDs must all be distinct."""
    ids = {Benchmark(source="cli", prompt="test").id for _ in range(100)}
    assert len(ids) == 100


@settings(max_examples=20)
@given(
    source=st.sampled_from(list(VALID_SOURCES)),
    prompt=st.text(min_size=1, max_size=100),
)
def test_ulid_format_property(source: str, prompt: str) -> None:
    """All generated Benchmark IDs match Crockford base32 format."""
    b = Benchmark(source=source, prompt=prompt)
    assert _CROCKFORD_PATTERN.match(b.id)


@pytest.mark.parametrize("delay_ms", [2])
def test_ulid_sortability(delay_ms: int) -> None:
    """Property 4: Sequentially created benchmarks have lexicographically ordered IDs."""
    b1 = Benchmark(source="cli", prompt="first")
    time.sleep(delay_ms / 1000.0)
    b2 = Benchmark(source="cli", prompt="second")
    assert b1.id < b2.id, f"Expected {b1.id} < {b2.id}"


@settings(max_examples=20)
@given(
    source=st.sampled_from(list(VALID_SOURCES)),
    prompt=st.text(min_size=1, max_size=200),
    status=st.sampled_from(list(BenchmarkStatus)),
)
def test_pydantic_serialization_roundtrip(
    source: str, prompt: str, status: BenchmarkStatus
) -> None:
    """Benchmark model survives JSON serialization and deserialization."""
    original = Benchmark(source=source, prompt=prompt, status=status)
    json_str = original.model_dump_json()
    restored = Benchmark.model_validate_json(json_str)
    assert restored.id == original.id
    assert restored.source == original.source
    assert restored.prompt == original.prompt
    assert restored.status == original.status
