"""PDF receipt owner action."""

from typing import BinaryIO, final

from .disposition import (
    PdfReceiptDisposition,
)
from .receiver import (
    PdfObjectReceiver,
)
from .repository import (
    PdfReceiptRepository,
)
from .request import (
    ReceivePdfRequest,
)
from .result import (
    ReceivePdfResult,
)


@final
class ReceivePdf:
    """Coordinate byte receipt and immutable source observation."""

    __slots__ = ("_objects", "_repository")

    def __init__(
        self,
        *,
        objects: PdfObjectReceiver,
        repository: PdfReceiptRepository,
    ) -> None:
        self._objects = objects
        self._repository = repository

    def receive(
        self, *, request: ReceivePdfRequest, stream: BinaryIO
    ) -> ReceivePdfResult:
        document = self._objects.receive(
            stream=stream, declared_byte_size=request.declared_byte_size
        )
        effect = self._repository.record_pdf_receipt(
            document=document, source_link=request.source_link
        )
        if document.created or effect.document_created:
            disposition = PdfReceiptDisposition.RECEIVED
        elif effect.receipt_created:
            disposition = PdfReceiptDisposition.SOURCE_OBSERVATION_ADDED
        else:
            disposition = PdfReceiptDisposition.ALREADY_PRESENT
        return ReceivePdfResult(
            receipt_id=effect.receipt_id,
            sha256=document.sha256,
            byte_size=document.byte_size,
            disposition=disposition,
        )
