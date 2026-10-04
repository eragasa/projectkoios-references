"""PDF receipt result."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionResult

from ...base import (
    AbstractDocumentReferenceDataObject,
)
from ...constants import MAX_PDF_BYTES
from .disposition import (
    PdfReceiptDisposition,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceivePdfResult(
    AbstractDocumentReferenceDataObject, DataObjectActionResult
):
    """Report durable PDF receipt without returning a path."""

    receipt_id: str
    sha256: str
    byte_size: int
    disposition: PdfReceiptDisposition

    def __post_init__(self) -> None:
        self._validate_receipt_id(self.receipt_id)
        self._validate_sha256(self.sha256)
        if (
            type(self.byte_size) is not int
            or not 1 <= self.byte_size <= MAX_PDF_BYTES
        ):
            raise ValueError("byte_size is outside the supported PDF range")
        if type(self.disposition) is not PdfReceiptDisposition:
            raise ValueError("disposition must be a PdfReceiptDisposition")
