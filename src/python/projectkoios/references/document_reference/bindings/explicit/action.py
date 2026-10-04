"""Explicit reference/document binding action."""

from typing import final

from projectkoios.base import DataObjectActionizer

from ..basis import (
    ReferenceDocumentLinkageBasis,
)
from ..repository import (
    ReferenceDocumentBindingRepository,
)
from ..result import (
    BindPdfToReferenceResult,
)
from ..selection import (
    ReferenceDocumentBindingSelection,
)
from .request import (
    BindPdfToReferenceRequest,
)


@final
class BindPdfToReference(
    DataObjectActionizer[BindPdfToReferenceRequest, BindPdfToReferenceResult]
):
    """Create an explicit one-to-one binding or return an exact retry."""

    __slots__ = ("_repository",)

    def __init__(
        self,
        *,
        repository: ReferenceDocumentBindingRepository,
    ) -> None:
        self._repository = repository

    def action(
        self, *, request: BindPdfToReferenceRequest
    ) -> BindPdfToReferenceResult:
        return self._repository.bind_reference_document(
            selection=ReferenceDocumentBindingSelection(
                collection_id=request.collection_id,
                citekey=request.citekey,
                document_sha256=request.document_sha256,
                linkage_basis=ReferenceDocumentLinkageBasis.EXPLICIT_SELECTION,
            )
        )
