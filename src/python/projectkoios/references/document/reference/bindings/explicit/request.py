"""Explicit PDF binding request."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionRequest

from ...base import (
    AbstractDocumentReferenceDataObject,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BindPdfToReferenceRequest(
    AbstractDocumentReferenceDataObject, DataObjectActionRequest
):
    """Select a PDF and required member explicitly."""

    collection_id: str
    citekey: str
    document_sha256: str

    def __post_init__(self) -> None:
        self._validate_identifier(self.collection_id, field="collection_id")
        self._validate_identifier(self.citekey, field="citekey")
        self._validate_sha256(self.document_sha256, field="document_sha256")
