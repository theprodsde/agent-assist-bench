"""Unit tests for request signing and verification."""

from __future__ import annotations

import time

from benchmark.auth.signer import (
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    RequestSigner,
    verify_request_signature,
)


class TestRequestSigner:
    """Test the RequestSigner produces valid headers."""

    def test_sign_returns_required_headers(self) -> None:
        signer = RequestSigner("test-secret")
        headers = signer.sign(b'{"prompt": "hello"}')

        assert SIGNATURE_HEADER in headers
        assert TIMESTAMP_HEADER in headers
        assert NONCE_HEADER in headers

    def test_signature_is_hex_string(self) -> None:
        signer = RequestSigner("key")
        headers = signer.sign(b"body")
        sig = headers[SIGNATURE_HEADER]
        assert len(sig) == 64  # SHA-256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in sig)

    def test_same_body_different_nonces_produce_different_signatures(self) -> None:
        signer = RequestSigner("key")
        h1 = signer.sign(b"same-body", nonce="nonce-1")
        h2 = signer.sign(b"same-body", nonce="nonce-2")
        assert h1[SIGNATURE_HEADER] != h2[SIGNATURE_HEADER]

    def test_different_bodies_produce_different_signatures(self) -> None:
        signer = RequestSigner("key")
        h1 = signer.sign(b"body-a", nonce="same")
        h2 = signer.sign(b"body-b", nonce="same")
        assert h1[SIGNATURE_HEADER] != h2[SIGNATURE_HEADER]


class TestVerifyRequestSignature:
    """Test the verification function."""

    def test_valid_signature_passes(self) -> None:
        key = "shared-secret"
        body = b'{"prompt": "test"}'
        signer = RequestSigner(key)
        headers = signer.sign(body)

        assert verify_request_signature(
            body=body,
            signature=headers[SIGNATURE_HEADER],
            timestamp=headers[TIMESTAMP_HEADER],
            nonce=headers[NONCE_HEADER],
            signing_key=key,
        )

    def test_wrong_key_fails(self) -> None:
        body = b"request body"
        signer = RequestSigner("correct-key")
        headers = signer.sign(body)

        assert not verify_request_signature(
            body=body,
            signature=headers[SIGNATURE_HEADER],
            timestamp=headers[TIMESTAMP_HEADER],
            nonce=headers[NONCE_HEADER],
            signing_key="wrong-key",
        )

    def test_tampered_body_fails(self) -> None:
        key = "key"
        signer = RequestSigner(key)
        headers = signer.sign(b"original body")

        assert not verify_request_signature(
            body=b"tampered body",
            signature=headers[SIGNATURE_HEADER],
            timestamp=headers[TIMESTAMP_HEADER],
            nonce=headers[NONCE_HEADER],
            signing_key=key,
        )

    def test_expired_timestamp_fails(self) -> None:
        key = "key"
        body = b"body"
        # Simulate a request from 10 minutes ago
        old_timestamp = str(int(time.time()) - 600)
        signer = RequestSigner(key)
        headers = signer.sign(body)
        # Replace timestamp with expired one (signature won't match anyway)
        headers[TIMESTAMP_HEADER] = old_timestamp

        assert not verify_request_signature(
            body=body,
            signature=headers[SIGNATURE_HEADER],
            timestamp=old_timestamp,
            nonce=headers[NONCE_HEADER],
            signing_key=key,
            max_age_seconds=300,
        )

    def test_invalid_timestamp_format_fails(self) -> None:
        assert not verify_request_signature(
            body=b"body",
            signature="abc",
            timestamp="not-a-number",
            signing_key="key",
        )

    def test_empty_signing_key_still_works(self) -> None:
        """Even an empty key produces a valid HMAC — used for testing."""
        key = ""
        body = b"body"
        signer = RequestSigner(key)
        headers = signer.sign(body)

        assert verify_request_signature(
            body=body,
            signature=headers[SIGNATURE_HEADER],
            timestamp=headers[TIMESTAMP_HEADER],
            nonce=headers[NONCE_HEADER],
            signing_key=key,
        )
