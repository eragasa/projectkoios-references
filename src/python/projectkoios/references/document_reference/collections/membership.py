"""Reference collection membership."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ..base import (
    AbstractDocumentReferenceDataObject,
)
from .pdf_requirement import (
    PdfRequirement,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceCollectionMembership(
    AbstractDocumentReferenceDataObject, DataObjectModel
):
    """Declare one citekey's PDF requirement within one collection."""

    collection_id: str
    citekey: str
    pdf_requirement: PdfRequirement

    def __post_init__(self) -> None:
        self._validate_identifier(self.collection_id, field="collection_id")
        self._validate_identifier(self.citekey, field="citekey")
        if type(self.pdf_requirement) is not PdfRequirement:
            raise ValueError("pdf_requirement must be a PdfRequirement")
