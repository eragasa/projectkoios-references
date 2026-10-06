"""Missing-PDF list request."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionRequest

from ...base import (
    AbstractDocumentReferenceDataObject,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMissingPdfReferencesRequest(
    AbstractDocumentReferenceDataObject, DataObjectActionRequest
):
    """Select one collection for missing-PDF derivation."""

    collection_id: str

    def __post_init__(self) -> None:
        self._validate_identifier(self.collection_id, field="collection_id")
