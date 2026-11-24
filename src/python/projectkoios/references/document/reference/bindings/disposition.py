"""Binding dispositions."""

from enum import StrEnum


class BindingDisposition(StrEnum):
    """Describe the idempotent effect of one binding request."""

    BOUND = "bound"
    ALREADY_BOUND = "already-bound"
