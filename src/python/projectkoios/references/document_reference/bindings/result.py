"""Reference/document binding result."""

from dataclasses import dataclass

from projectkoios.base import DataObjectActionResult

from ..base import (
    AbstractDocumentReferenceDataObject,
)
from .binding import (
    ReferenceDocumentBinding,
)
from .disposition import (
    BindingDisposition,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BindPdfToReferenceResult(
    AbstractDocumentReferenceDataObject, DataObjectActionResult
):
    """Report the effect of one atomic binding attempt."""

    binding: ReferenceDocumentBinding
    disposition: BindingDisposition

    def __post_init__(self) -> None:
        if type(self.binding) is not ReferenceDocumentBinding:
            raise ValueError("binding must be a ReferenceDocumentBinding")
        if type(self.disposition) is not BindingDisposition:
            raise ValueError("disposition must be a BindingDisposition")
