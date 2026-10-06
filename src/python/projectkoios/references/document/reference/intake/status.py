"""Composed reference-PDF provision outcomes."""

from enum import StrEnum


class ReferencePdfProvisionStatus(StrEnum):
    """Describe receipt and binding without hiding partial custody."""

    BOUND = "bound"
    ALREADY_BOUND = "already-bound"
    RECEIVED_UNBOUND = "received-unbound"
