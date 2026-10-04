"""Reference collection provenance."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ..base import (
    AbstractDocumentReferenceDataObject,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceCollection(AbstractDocumentReferenceDataObject, DataObjectModel):
    """Identify a collection and its source revision provenance."""

    collection_id: str
    source_id: str
    source_revision: str

    def __post_init__(self) -> None:
        self._validate_identifier(self.collection_id, field="collection_id")
        if (
            type(self.source_id) is not str
            or not 1 <= len(self.source_id) <= 1000
        ):
            raise ValueError("source_id must contain 1-1000 characters")
        if (
            type(self.source_revision) is not str
            or not 1 <= len(self.source_revision) <= 200
        ):
            raise ValueError("source_revision must contain 1-200 characters")
