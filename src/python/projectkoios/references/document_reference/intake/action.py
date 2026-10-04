"""Composed reference-PDF provision action."""

from typing import BinaryIO, final

from ..bindings.disposition import (
    BindingDisposition,
)
from ..bindings.errors import (
    ReferenceDocumentBindingConflict,
)
from ..bindings.explicit.action import (
    BindPdfToReference,
)
from ..bindings.explicit.request import (
    BindPdfToReferenceRequest,
)
from ..documents.receipt.action import (
    ReceivePdf,
)
from ..documents.receipt.request import (
    ReceivePdfRequest,
)
from .request import (
    ProvideReferencePdfRequest,
)
from .result import (
    ProvideReferencePdfResult,
)
from .status import (
    ReferencePdfProvisionStatus,
)


@final
class ProvideReferencePdf:
    """Receive bytes and represent explicit binding conflict honestly."""

    __slots__ = ("_bind", "_receive")

    def __init__(
        self, *, receive: ReceivePdf, bind: BindPdfToReference
    ) -> None:
        self._receive = receive
        self._bind = bind

    def provide(
        self, *, request: ProvideReferencePdfRequest, stream: BinaryIO
    ) -> ProvideReferencePdfResult:
        receipt = self._receive.receive(
            request=ReceivePdfRequest(
                source_link=request.source_link,
                declared_byte_size=request.declared_byte_size,
            ),
            stream=stream,
        )
        try:
            binding = self._bind.action(
                request=BindPdfToReferenceRequest(
                    collection_id=request.collection_id,
                    citekey=request.citekey,
                    document_sha256=receipt.sha256,
                )
            )
        except ReferenceDocumentBindingConflict:
            return ProvideReferencePdfResult(
                receipt=receipt,
                binding=None,
                status=ReferencePdfProvisionStatus.RECEIVED_UNBOUND,
            )
        status = (
            ReferencePdfProvisionStatus.BOUND
            if binding.disposition is BindingDisposition.BOUND
            else ReferencePdfProvisionStatus.ALREADY_BOUND
        )
        return ProvideReferencePdfResult(
            receipt=receipt, binding=binding, status=status
        )
