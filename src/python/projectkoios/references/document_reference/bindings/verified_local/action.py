"""Verified local evidence binding action."""

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
    BindVerifiedLocalEvidenceRequest,
)


@final
class BindVerifiedLocalEvidence(
    DataObjectActionizer[
        BindVerifiedLocalEvidenceRequest, BindPdfToReferenceResult
    ]
):
    """Bind one plan-verified local document during import."""

    __slots__ = ("_repository",)

    def __init__(
        self,
        *,
        repository: ReferenceDocumentBindingRepository,
    ) -> None:
        self._repository = repository

    def action(
        self, *, request: BindVerifiedLocalEvidenceRequest
    ) -> BindPdfToReferenceResult:
        return self._repository.bind_reference_document(
            selection=ReferenceDocumentBindingSelection(
                collection_id=request.collection_id,
                citekey=request.citekey,
                document_sha256=request.document_sha256,
                linkage_basis=ReferenceDocumentLinkageBasis.VERIFIED_LOCAL_EVIDENCE_IMPORT,
            )
        )
