"""Reference collection failures."""

from ..errors import (
    DocumentReferenceError,
)


class UnknownCollection(DocumentReferenceError):
    """The requested collection is not present."""


class UnknownReference(DocumentReferenceError):
    """The requested citekey is not present in the selected collection."""
