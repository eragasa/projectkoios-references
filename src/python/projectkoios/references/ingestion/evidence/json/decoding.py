from __future__ import annotations

import json

from ..contract import REFERENCE_EVIDENCE_MAX_BYTES
from ..error import (
    IngestionEvidenceError,
    IngestionEvidenceLimitError,
    IngestionEvidenceParseError,
)

_MAX_JSON_DEPTH = 64
_MAX_STRING_CHARACTERS = 4_096


def parse_json_bytes(content: bytes) -> object:
    if not isinstance(content, bytes):
        raise TypeError("reference evidence must be bytes")
    if len(content) > REFERENCE_EVIDENCE_MAX_BYTES:
        raise IngestionEvidenceLimitError(
            "reference evidence exceeds the size limit"
        )
    try:
        text = content.decode("utf-8", errors="strict")
        require_bounded_json_nesting(text)
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except IngestionEvidenceError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise IngestionEvidenceParseError(
            f"reference evidence is malformed JSON: {error}"
        ) from error


def require_mapping(
    value: object, name: str, fields: set[str]
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} field names must be strings")
    actual = set(value)
    unknown = actual - fields
    missing = fields - actual
    if unknown:
        raise ValueError(f"{name} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")
    return value


def require_list(value: object, name: str, maximum: int) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    if len(value) > maximum:
        raise IngestionEvidenceLimitError(f"{name} exceeds the item limit")
    return value


def require_string_tuple(
    value: object, name: str, maximum: int
) -> tuple[str, ...]:
    return tuple(
        require_text(item, f"{name}[{index}]")
        for index, item in enumerate(require_list(value, name, maximum))
    )


def require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > _MAX_STRING_CHARACTERS:
        raise IngestionEvidenceLimitError(f"{name} exceeds the string limit")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must be valid UTF-8") from error
    return value


def require_sha256(value: object, name: str) -> str:
    digest = require_text(value, name)
    if len(digest) != 64 or digest != digest.lower():
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    try:
        int(digest, 16)
    except ValueError as error:
        raise ValueError(
            f"{name} must be a lowercase SHA-256 digest"
        ) from error
    return digest


def require_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def require_boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be boolean")
    return value


def _object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def require_bounded_json_nesting(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise IngestionEvidenceLimitError(
                    "reference-evidence JSON exceeds the depth limit"
                )
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError(
                    "reference-evidence JSON nesting is unbalanced"
                )
    if in_string or depth != 0:
        raise ValueError("reference-evidence JSON nesting is incomplete")
