"""Composed reference-PDF provision result."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionResult

from ..base import (
    AbstractDocumentReferenceDataObject,
)
from ..bindings.disposition import BindingDisposition
from ..bindings.result import (
    BindPdfToReferenceResult,
)
from ..documents.receipt.result import (
    ReceivePdfResult,
)
from .status import (
    ReferencePdfProvisionStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProvideReferencePdfResult(
    AbstractDocumentReferenceDataObject, DataObjectActionResult
):
    """Report custody and binding without hiding partial success."""

    receipt: ReceivePdfResult
    binding: BindPdfToReferenceResult | None
    status: ReferencePdfProvisionStatus

    def __post_init__(self) -> None:
        if type(self.receipt) is not ReceivePdfResult:
            raise ValueError("receipt must be a ReceivePdfResult")
        if (
            self.binding is not None
            and type(self.binding) is not BindPdfToReferenceResult
        ):
            raise ValueError("binding must be a binding result or None")
        if type(self.status) is not ReferencePdfProvisionStatus:
            raise ValueError("status must be a ReferencePdfProvisionStatus")
        if (self.status is ReferencePdfProvisionStatus.RECEIVED_UNBOUND) != (
            self.binding is None
        ):
            raise ValueError("provision status does not match binding presence")
        expected_disposition = {
            ReferencePdfProvisionStatus.BOUND: BindingDisposition.BOUND,
            ReferencePdfProvisionStatus.ALREADY_BOUND: (
                BindingDisposition.ALREADY_BOUND
            ),
        }.get(self.status)
        if (
            self.binding is not None
            and self.binding.disposition is not expected_disposition
        ):
            raise ValueError("provision status does not match disposition")
