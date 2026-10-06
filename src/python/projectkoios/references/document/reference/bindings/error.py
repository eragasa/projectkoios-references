"""Reference/document binding conflict."""

from ..errors import (
    DocumentReferenceError,
)


class ReferenceDocumentBindingConflict(DocumentReferenceError):
    """A requested one-to-one binding conflicts with an existing binding."""
