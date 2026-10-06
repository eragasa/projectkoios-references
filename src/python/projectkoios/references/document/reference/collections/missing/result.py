"""Missing-PDF list result."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionResult

from ...base import (
    AbstractDocumentReferenceDataObject,
)
from ...constants import (
    MAX_COLLECTION_MEMBERS,
)
from .item import (
    MissingPdfReference,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMissingPdfReferencesResult(
    AbstractDocumentReferenceDataObject, DataObjectActionResult
):
    """Return a bounded missing list and aggregate counts."""

    collection_id: str
    source_id: str
    source_revision: str
    required_count: int
    bound_count: int
    not_applicable_count: int
    missing: tuple[MissingPdfReference, ...]

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
        if type(self.missing) is not tuple or any(
            type(item) is not MissingPdfReference for item in self.missing
        ):
            raise ValueError("missing must contain MissingPdfReference values")
        if len(self.missing) > MAX_COLLECTION_MEMBERS:
            raise ValueError("missing list exceeds the collection member cap")
        if any(
            type(value) is not int or value < 0
            for value in (
                self.required_count,
                self.bound_count,
                self.not_applicable_count,
            )
        ):
            raise ValueError("collection counts must be non-negative integers")
        if self.required_count != self.bound_count + len(self.missing):
            raise ValueError(
                "required count does not match bound and missing rows"
            )
