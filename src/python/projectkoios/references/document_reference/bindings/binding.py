"""Immutable reference/document binding."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ..base import (
    AbstractDocumentReferenceDataObject,
)
from .basis import (
    ReferenceDocumentLinkageBasis,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentBinding(
    AbstractDocumentReferenceDataObject, DataObjectModel
):
    """Identify one immutable neutral binding."""

    binding_id: str
    citekey: str
    document_sha256: str
    linkage_basis: ReferenceDocumentLinkageBasis

    def __post_init__(self) -> None:
        self._validate_binding_id(self.binding_id)
        self._validate_identifier(self.citekey, field="citekey")
        self._validate_sha256(self.document_sha256, field="document_sha256")
        if type(self.linkage_basis) is not ReferenceDocumentLinkageBasis:
            raise ValueError("linkage_basis must be owner resolved")
