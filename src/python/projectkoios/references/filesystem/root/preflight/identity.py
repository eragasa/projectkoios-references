from __future__ import annotations

import re


def validate_probe_id(value: object) -> str:
    """Return one valid placeholder-probe identity."""
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value) is None
    ):
        raise ValueError("placeholder probe identity is invalid")
    return value
