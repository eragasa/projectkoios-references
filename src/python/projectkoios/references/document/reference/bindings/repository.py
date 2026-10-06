"""Reference/document binding persistence port."""

from typing import Protocol

from .result import (
    BindPdfToReferenceResult,
)
from .selection import (
    ReferenceDocumentBindingSelection,
)


class ReferenceDocumentBindingRepository(Protocol):
    """Persist owner-resolved one-to-one bindings."""

    def bind_reference_document(
        self,
        *,
        selection: ReferenceDocumentBindingSelection,
    ) -> BindPdfToReferenceResult: ...
