"""Missing-PDF derivation action."""

from typing import final

from projectkoios.base import DataObjectActionizer

from .repository import (
    MissingPdfReferencesRepository,
)
from .request import (
    ListMissingPdfReferencesRequest,
)
from .result import (
    ListMissingPdfReferencesResult,
)


@final
class ListMissingPdfReferences(
    DataObjectActionizer[
        ListMissingPdfReferencesRequest, ListMissingPdfReferencesResult
    ]
):
    """Derive missing PDFs from membership and bindings."""

    __slots__ = ("_repository",)

    def __init__(self, *, repository: MissingPdfReferencesRepository) -> None:
        self._repository = repository

    def action(
        self, *, request: ListMissingPdfReferencesRequest
    ) -> ListMissingPdfReferencesResult:
        return self._repository.list_missing_pdf_references(
            collection_id=request.collection_id
        )
