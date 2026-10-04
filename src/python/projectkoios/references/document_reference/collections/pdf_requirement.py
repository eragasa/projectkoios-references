"""PDF requirement values."""

from enum import StrEnum


class PdfRequirement(StrEnum):
    """Declare whether one collection member should have a PDF."""

    REQUIRED = "required"
    NOT_APPLICABLE = "not-applicable"
