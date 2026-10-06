"""PDF receipt request."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionRequest

from ...base import (
    AbstractDocumentReferenceDataObject,
)
from ...constants import MAX_PDF_BYTES


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceivePdfRequest(
    AbstractDocumentReferenceDataObject, DataObjectActionRequest
):
    """Describe source evidence accompanying a streamed PDF."""

    source_link: str | None = None
    declared_byte_size: int | None = None

    def __post_init__(self) -> None:
        self._validate_source_link(self.source_link)
        if self.declared_byte_size is not None and (
            type(self.declared_byte_size) is not int
            or not 1 <= self.declared_byte_size <= MAX_PDF_BYTES
        ):
            raise ValueError(
                "declared_byte_size is outside the supported PDF range"
            )
