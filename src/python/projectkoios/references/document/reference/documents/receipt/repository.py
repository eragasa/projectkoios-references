"""PDF receipt persistence port."""

from typing import Protocol

from ..pdf.stored import (
    StoredPdfObject,
)
from .effect import (
    ReceiptRecordEffect,
)


class PdfReceiptRepository(Protocol):
    """Persist document identity and immutable source observations."""

    def record_pdf_receipt(
        self,
        *,
        document: StoredPdfObject,
        source_link: str | None,
    ) -> ReceiptRecordEffect: ...
