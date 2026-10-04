"""Owner-resolved binding selection."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ..base import (
    AbstractDocumentReferenceDataObject,
)
from .basis import (
    ReferenceDocumentLinkageBasis,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentBindingSelection(
    AbstractDocumentReferenceDataObject, DataObjectModel
):
    """Carry owner-selected linkage provenance to persistence."""

    collection_id: str
    citekey: str
    document_sha256: str
    linkage_basis: ReferenceDocumentLinkageBasis

    def __post_init__(self) -> None:
        self._validate_identifier(self.collection_id, field="collection_id")
        self._validate_identifier(self.citekey, field="citekey")
        self._validate_sha256(self.document_sha256, field="document_sha256")
        if type(self.linkage_basis) is not ReferenceDocumentLinkageBasis:
            raise ValueError("linkage_basis must be owner resolved")
