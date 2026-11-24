from __future__ import annotations

import unicodedata

from .error import CitationKeyError

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


def validate_citekey(value: object, *, field: str = "citekey") -> str:
    """Return one literal citation key accepted by the owner grammar."""
    if not isinstance(value, str) or not value:
        raise CitationKeyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise CitationKeyError(f"{field} must use NFC normalization")
    if len(value) > _CITEKEY_MAX_LENGTH:
        raise CitationKeyError(f"{field} exceeds the portable length limit")
    if not value[0].isascii() or not value[0].isalpha():
        raise CitationKeyError(f"{field} must start with an ASCII letter")
    if any(character not in _CITEKEY_ASCII for character in value):
        raise CitationKeyError(
            f"{field} may contain only ASCII letters, numbers, period, "
            "underscore, or hyphen"
        )
    if value.endswith("."):
        raise CitationKeyError(f"{field} must not end with a period")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise CitationKeyError(f"{field} is a reserved portable filename")
    return value
