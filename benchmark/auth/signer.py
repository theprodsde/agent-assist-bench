"""HMAC-SHA256 request signing for benchmark-to-agent authentication.

Ensures that only the benchmark runner (which holds the signing key) can
make valid requests to agent endpoints. The agent verifies the signature
before processing any request.

Usage in the benchmark runner (client side):
    signer = RequestSigner(signing_key="shared-secret")
    headers = signer.sign(body=request_bytes)
    # headers includes X-Benchmark-Signature and X-Benchmark-Timestamp

Usage in the agent container (server side):
    is_valid = verify_request_signature(
        body=request_body,
        signature=request.headers["X-Benchmark-Signature"],
        timestamp=request.headers["X-Benchmark-Timestamp"],
        signing_key="shared-secret",
        max_age_seconds=300,
    )
"""

from __future__ import annotations

import hashlib
import hmac
import time

# Header names used for signature transport
SIGNATURE_HEADER = "X-Benchmark-Signature"
TIMESTAMP_HEADER = "X-Benchmark-Timestamp"
NONCE_HEADER = "X-Benchmark-Nonce"


class RequestSigner:
    """Signs outbound benchmark requests with HMAC-SHA256.

    The signature covers: timestamp + nonce + request body.
    This prevents replay attacks (timestamp expiry) and ensures
    request integrity (body is part of the signed payload).
    """

    def __init__(self, signing_key: str) -> None:
        self._key = signing_key.encode("utf-8")

    def sign(self, body: bytes, nonce: str | None = None) -> dict[str, str]:
        """Generate authentication headers for a request body.

        Returns a dict of headers to include in the HTTP request:
          - X-Benchmark-Signature: HMAC-SHA256 hex digest
          - X-Benchmark-Timestamp: Unix timestamp (seconds)
          - X-Benchmark-Nonce: Unique request identifier (optional replay guard)
        """
        timestamp = str(int(time.time()))
        if nonce is None:
            nonce = hashlib.sha256(f"{timestamp}{id(body)}".encode()).hexdigest()[:16]

        # Signed payload: timestamp|nonce|body
        payload = f"{timestamp}|{nonce}|".encode() + body
        signature = hmac.new(self._key, payload, hashlib.sha256).hexdigest()

        return {
            SIGNATURE_HEADER: signature,
            TIMESTAMP_HEADER: timestamp,
            NONCE_HEADER: nonce,
        }


def verify_request_signature(
    *,
    body: bytes,
    signature: str,
    timestamp: str,
    nonce: str = "",
    signing_key: str,
    max_age_seconds: int = 300,
) -> bool:
    """Verify that a request was signed by the benchmark runner.

    Checks:
    1. Timestamp is within max_age_seconds of current time (prevents replay)
    2. HMAC-SHA256 signature matches the expected value (proves authenticity)

    Args:
        body: Raw request body bytes
        signature: Value of X-Benchmark-Signature header
        timestamp: Value of X-Benchmark-Timestamp header
        nonce: Value of X-Benchmark-Nonce header (empty string if not provided)
        signing_key: The shared secret (must match what RequestSigner uses)
        max_age_seconds: Maximum allowed age of the request (default 5 minutes)

    Returns:
        True if the request is valid and authentic, False otherwise.
    """
    # Check timestamp freshness
    try:
        request_time = int(timestamp)
    except (ValueError, TypeError):
        return False

    current_time = int(time.time())
    if abs(current_time - request_time) > max_age_seconds:
        return False

    # Reconstruct expected signature
    key = signing_key.encode("utf-8")
    payload = f"{timestamp}|{nonce}|".encode() + body
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(signature, expected)
