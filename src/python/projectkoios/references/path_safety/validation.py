"""Portable citation-key and relative-path validation."""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath

from projectkoios.references.path_safety import errors

_CITEKEY_MAX_LENGTH = 200
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
_CITEKEY_ASCII = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_PORTABLE_FORBIDDEN = frozenset('<>:"\\|?*')


class PortablePathValidator:
    """Own validation shared by portable root aliases and path segments."""

    __slots__ = ()

    @staticmethod
    def validate_segment(*, value: str, field: str) -> None:
        """Reject traversal, reserved names, and nonportable characters."""
        if value in {"", ".", ".."}:
            raise errors.PathSafetyError(
                f"{field} contains an invalid path segment"
            )
        if value.endswith((" ", ".")):
            raise errors.PathSafetyError(
                f"{field} contains a segment ending with space or period"
            )
        if any(
            ord(character) < 32 or character in _PORTABLE_FORBIDDEN
            for character in value
        ):
            raise errors.PathSafetyError(
                f"{field} contains a nonportable filename character"
            )
        stem = value.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise errors.PathSafetyError(
                f"{field} contains a reserved filename segment"
            )


def validate_citekey(value: object, *, field: str = "citekey") -> str:
    """Return one literal citation key accepted by the owner grammar."""
    if not isinstance(value, str) or not value:
        raise errors.PathSafetyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise errors.PathSafetyError(f"{field} must use NFC normalization")
    if len(value) > _CITEKEY_MAX_LENGTH:
        raise errors.PathSafetyError(
            f"{field} exceeds the portable length limit"
        )
    if not value[0].isascii() or not value[0].isalpha():
        raise errors.PathSafetyError(f"{field} must start with an ASCII letter")
    if any(character not in _CITEKEY_ASCII for character in value):
        raise errors.PathSafetyError(
            f"{field} may contain only ASCII letters, numbers, period, "
            "underscore, or hyphen"
        )
    if value.endswith("."):
        raise errors.PathSafetyError(f"{field} must not end with a period")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise errors.PathSafetyError(f"{field} is a reserved portable filename")
    return value


def validate_root_alias(value: object, *, field: str = "root_alias") -> str:
    """Return one portable root-alias segment."""
    if not isinstance(value, str) or not value:
        raise errors.PathSafetyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise errors.PathSafetyError(f"{field} must use NFC normalization")
    if len(value) > 100:
        raise errors.PathSafetyError(
            f"{field} exceeds the portable length limit"
        )
    if "/" in value or "\\" in value:
        raise errors.PathSafetyError(
            f"{field} must be one portable path segment"
        )
    PortablePathValidator.validate_segment(value=value, field=field)
    return value


def validate_relative_path(
    value: str | PurePosixPath,
    *,
    field: str = "relative_path",
) -> PurePosixPath:
    """Return a normalized portable relative path without traversal."""
    raw = value.as_posix() if isinstance(value, PurePosixPath) else value
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise errors.PathSafetyError(
            f"{field} must be a normalized portable relative path"
        )
    if raw != unicodedata.normalize("NFC", raw):
        raise errors.PathSafetyError(f"{field} must use NFC normalization")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise errors.PathSafetyError(
            f"{field} must be normalized, relative, and traversal-free"
        )
    for part in path.parts:
        PortablePathValidator.validate_segment(value=part, field=field)
    return path
