"""PDF receipt dispositions."""

from enum import StrEnum


class PdfReceiptDisposition(StrEnum):
    """Describe the idempotent effect of one PDF receipt."""

    RECEIVED = "received"
    SOURCE_OBSERVATION_ADDED = "source-observation-added"
    ALREADY_PRESENT = "already-present"
