"""PDF object receipt port."""

from typing import BinaryIO, Protocol

from ..pdf.stored import (
    StoredPdfObject,
)


class PdfObjectReceiver(Protocol):
    """Receive bounded content-addressed PDF bytes."""

    def receive(
        self, *, stream: BinaryIO, declared_byte_size: int | None
    ) -> StoredPdfObject: ...
