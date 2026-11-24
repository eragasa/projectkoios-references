from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath

from .error import FilesystemPathError

_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_PORTABLE_FORBIDDEN = frozenset('<>:"\\|?*')


def _validate_segment(*, value: str, field: str) -> None:
    if value in {"", ".", ".."}:
        raise FilesystemPathError(f"{field} contains an invalid path segment")
    if value.endswith((" ", ".")):
        raise FilesystemPathError(
            f"{field} contains a segment ending with space or period"
        )
    if any(
        ord(character) < 32 or character in _PORTABLE_FORBIDDEN
        for character in value
    ):
        raise FilesystemPathError(
            f"{field} contains a nonportable filename character"
        )
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise FilesystemPathError(
            f"{field} contains a reserved filename segment"
        )


def validate_root_alias(value: object, *, field: str = "root_alias") -> str:
    if not isinstance(value, str) or not value:
        raise FilesystemPathError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise FilesystemPathError(f"{field} must use NFC normalization")
    if len(value) > 100:
        raise FilesystemPathError(f"{field} exceeds the portable length limit")
    if "/" in value or "\\" in value:
        raise FilesystemPathError(f"{field} must be one portable path segment")
    _validate_segment(value=value, field=field)
    return value


def validate_relative_path(
    value: str | PurePosixPath,
    *,
    field: str = "relative_path",
) -> PurePosixPath:
    raw = value.as_posix() if isinstance(value, PurePosixPath) else value
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise FilesystemPathError(
            f"{field} must be a normalized portable relative path"
        )
    if raw != unicodedata.normalize("NFC", raw):
        raise FilesystemPathError(f"{field} must use NFC normalization")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise FilesystemPathError(
            f"{field} must be normalized, relative, and traversal-free"
        )
    for part in path.parts:
        _validate_segment(value=part, field=field)
    return path
