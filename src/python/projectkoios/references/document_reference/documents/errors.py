"""Stored document failures."""

from ..errors import (
    DocumentReferenceError,
)


class UnknownDocument(DocumentReferenceError):
    """The requested document digest is not present."""


class DocumentContentConflict(DocumentReferenceError):
    """Stored bytes disagree with their SHA-addressed identity."""
