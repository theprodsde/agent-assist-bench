"""JSON codec for lossless SQLite serialization of benchmark payloads.

SQLite stores the JSON columns as text.  Bytes are represented with an explicit
versioned tag so they can be reconstructed without decoding or truncation.
"""

from __future__ import annotations

import base64
import json
from typing import Any

_BYTES_TAG = "__aab_codec__"
_BYTES_VERSION = "bytes-v1"
_BYTES_VALUE = "value"
_DICT_VERSION = "dict-v1"
_DICT_ITEMS = "items"


def _encode(value: Any) -> Any:
    """Convert values to JSON-safe values while retaining bytes exactly."""
    if isinstance(value, bytes):
        return {
            _BYTES_TAG: _BYTES_VERSION,
            _BYTES_VALUE: base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, dict):
        return {
            _BYTES_TAG: _DICT_VERSION,
            _DICT_ITEMS: [[_encode(key), _encode(item)] for key, item in value.items()],
        }
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any) -> Any:
    """Restore tagged byte values from decoded JSON data."""
    if isinstance(value, dict):
        if value.get(_BYTES_TAG) == _BYTES_VERSION and set(value) == {_BYTES_TAG, _BYTES_VALUE}:
            return base64.b64decode(value[_BYTES_VALUE], validate=True)
        if (
            value.get(_BYTES_TAG) == _DICT_VERSION
            and set(value) == {_BYTES_TAG, _DICT_ITEMS}
            and isinstance(value[_DICT_ITEMS], list)
            and all(isinstance(pair, list) and len(pair) == 2 for pair in value[_DICT_ITEMS])
        ):
            return {_decode(key): _decode(item) for key, item in value[_DICT_ITEMS]}
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def dumps(value: Any) -> str:
    """Serialize a JSON-compatible value, including arbitrary bytes."""
    return json.dumps(_encode(value))


def loads(value: str | bytes | bytearray) -> Any:
    """Deserialize a codec payload and restore any encoded bytes."""
    return _decode(json.loads(value))
