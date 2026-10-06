"""Missing-PDF derivation port."""

from typing import Protocol

from .result import (
    ListMissingPdfReferencesResult,
)


class MissingPdfReferencesRepository(Protocol):
    """Derive missing PDFs from authoritative collection facts."""

    def list_missing_pdf_references(
        self,
        *,
        collection_id: str,
    ) -> ListMissingPdfReferencesResult: ...
