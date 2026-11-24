"""Durable PDF receipt record effect."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ...base import (
    AbstractDocumentReferenceDataObject,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptRecordEffect(AbstractDocumentReferenceDataObject, DataObjectModel):
    """Report whether durable receipt rows were inserted."""

    receipt_id: str
    document_created: bool
    receipt_created: bool

    def __post_init__(self) -> None:
        self._validate_receipt_id(self.receipt_id)
        if (
            type(self.document_created) is not bool
            or type(self.receipt_created) is not bool
        ):
            raise ValueError("receipt effects must be bool values")
