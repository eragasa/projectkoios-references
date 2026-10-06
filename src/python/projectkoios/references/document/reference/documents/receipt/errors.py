"""PDF receipt failures."""

from ...errors import (
    DocumentReferenceError,
)


class InvalidPdfUpload(DocumentReferenceError):
    """The supplied body is not an acceptable PDF byte stream."""


class PdfUploadTooLarge(InvalidPdfUpload):
    """The supplied upload exceeds the configured byte cap."""
