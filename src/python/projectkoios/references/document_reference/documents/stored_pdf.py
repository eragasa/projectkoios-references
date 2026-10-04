"""Stored PDF object identity."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ..base import (
    AbstractDocumentReferenceDataObject,
)
from ..constants import MAX_PDF_BYTES


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredPdfObject(AbstractDocumentReferenceDataObject, DataObjectModel):
    """Identify one verified SHA-addressed PDF object."""

    sha256: str
    byte_size: int
    created: bool

    def __post_init__(self) -> None:
        self._validate_sha256(self.sha256)
        if (
            type(self.byte_size) is not int
            or not 1 <= self.byte_size <= MAX_PDF_BYTES
        ):
            raise ValueError("byte_size is outside the supported PDF range")
        if type(self.created) is not bool:
            raise ValueError("created must be a bool")
