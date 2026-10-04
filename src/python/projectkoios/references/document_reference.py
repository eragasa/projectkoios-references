"""Small owning model for reference collections and SHA-addressed PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO, Protocol, final
from urllib.parse import urlsplit

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)

MAX_PDF_BYTES = 100_000_000
MAX_COLLECTION_MEMBERS = 10_000
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,199}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECEIPT_ID = re.compile(r"document-receipt:sha256:[0-9a-f]{64}")
_BINDING_ID = re.compile(r"reference-document-binding:sha256:[0-9a-f]{64}")
_ENTRY_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_BINDING_BASES = frozenset(
    {
        "explicit-reference-document-selection",
        "verified-local-evidence-import",
    }
)


class DocumentReferenceError(RuntimeError):
    """Base failure for document/reference operations."""


class UnknownCollection(DocumentReferenceError):
    """The requested collection is not present."""


class UnknownReference(DocumentReferenceError):
    """The requested citekey is not present in the selected collection."""


class UnknownDocument(DocumentReferenceError):
    """The requested document digest is not present."""


class InvalidPdfUpload(DocumentReferenceError):
    """The supplied upload is not an acceptable PDF byte stream."""


class PdfUploadTooLarge(InvalidPdfUpload):
    """The supplied upload exceeds the configured byte cap."""


class DocumentContentConflict(DocumentReferenceError):
    """Stored bytes disagree with their SHA-addressed identity."""


class ReferenceDocumentBindingConflict(DocumentReferenceError):
    """A requested one-to-one binding conflicts with an existing binding."""


class DocumentReferenceStoreError(DocumentReferenceError):
    """The durable store could not complete an operation safely."""


class BibliographyMetadataError(ValueError):
    """A bibliography entry cannot provide bounded display metadata."""


class PdfRequirement(StrEnum):
    """Declare whether one collection member should have a PDF."""

    REQUIRED = "required"
    NOT_APPLICABLE = "not-applicable"


class PdfReceiptDisposition(StrEnum):
    """Describe the idempotent effect of one PDF receipt."""

    RECEIVED = "received"
    SOURCE_OBSERVATION_ADDED = "source-observation-added"
    ALREADY_PRESENT = "already-present"


class BindingDisposition(StrEnum):
    """Describe the idempotent effect of one binding request."""

    BOUND = "bound"
    ALREADY_BOUND = "already-bound"


def validate_identifier(value: str, *, field: str) -> str:
    """Return one bounded identifier or raise a stable validation error."""
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be 1-200 ASCII identifier characters")
    return value


def validate_sha256(value: str, *, field: str = "sha256") -> str:
    """Return one lowercase SHA-256 digest."""
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def validate_source_link(value: str | None) -> str | None:
    """Accept only bounded public HTTP(S) links as source observations."""
    if value is None:
        return None
    if type(value) is not str or not 1 <= len(value) <= 2048:
        raise ValueError("source_link must contain 1-2048 characters")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("source_link must be an unauthenticated HTTP(S) URL")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRecord(DataObjectModel):
    """Store the complete BibTeX entry for one citekey."""

    citekey: str
    bibtex_entry: str

    def __post_init__(self) -> None:
        validate_identifier(self.citekey, field="citekey")
        if (
            type(self.bibtex_entry) is not str
            or not 1 <= len(self.bibtex_entry.encode("utf-8")) <= 262_144
        ):
            raise ValueError("bibtex_entry must contain 1-262144 UTF-8 bytes")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDisplayMetadata(DataObjectModel):
    """Hold vendor-neutral, privacy-reduced bibliography display fields."""

    citekey: str
    entry_type: str
    title: str | None
    authors: tuple[str, ...]
    year: str | None

    def __post_init__(self) -> None:
        validate_identifier(self.citekey, field="citekey")
        if (
            type(self.entry_type) is not str
            or _ENTRY_TYPE.fullmatch(self.entry_type) is None
        ):
            raise ValueError("entry_type must be a bounded BibTeX entry type")
        if self.title is not None and (
            type(self.title) is not str
            or not 1 <= len(self.title) <= 2_000
            or not self.title.isprintable()
        ):
            raise ValueError("title must be 1-2000 printable characters")
        if (
            type(self.authors) is not tuple
            or len(self.authors) > 100
            or any(
                type(author) is not str
                or not 1 <= len(author) <= 500
                or not author.isprintable()
                for author in self.authors
            )
        ):
            raise ValueError(
                "authors must contain at most 100 bounded printable names"
            )
        if self.year is not None and (
            type(self.year) is not str
            or not 1 <= len(self.year) <= 64
            or not self.year.isprintable()
        ):
            raise ValueError("year must be 1-64 printable characters")


class BibliographyMetadataReader(Protocol):
    """Read one exact bibliography entry through a vendor-neutral boundary."""

    def read(
        self,
        *,
        citekey: str,
        bibtex_entry: str,
    ) -> ReferenceDisplayMetadata: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceCollection(DataObjectModel):
    """Identify a collection and its source revision provenance."""

    collection_id: str
    source_id: str
    source_revision: str

    def __post_init__(self) -> None:
        validate_identifier(self.collection_id, field="collection_id")
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceCollectionMembership(DataObjectModel):
    """Declare one citekey's PDF requirement within one collection."""

    collection_id: str
    citekey: str
    pdf_requirement: PdfRequirement

    def __post_init__(self) -> None:
        validate_identifier(self.collection_id, field="collection_id")
        validate_identifier(self.citekey, field="citekey")
        if type(self.pdf_requirement) is not PdfRequirement:
            raise ValueError("pdf_requirement must be a PdfRequirement")


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredPdfObject(DataObjectModel):
    """Identify one verified SHA-addressed PDF object."""

    sha256: str
    byte_size: int
    created: bool

    def __post_init__(self) -> None:
        validate_sha256(self.sha256)
        if (
            type(self.byte_size) is not int
            or not 1 <= self.byte_size <= MAX_PDF_BYTES
        ):
            raise ValueError("byte_size is outside the supported PDF range")
        if type(self.created) is not bool:
            raise ValueError("created must be a bool")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceivePdfRequest(DataObjectActionRequest):
    """Describe source evidence accompanying a streamed PDF."""

    source_link: str | None = None
    declared_byte_size: int | None = None

    def __post_init__(self) -> None:
        validate_source_link(self.source_link)
        if self.declared_byte_size is not None and (
            type(self.declared_byte_size) is not int
            or not 1 <= self.declared_byte_size <= MAX_PDF_BYTES
        ):
            raise ValueError(
                "declared_byte_size is outside the supported PDF range"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceivePdfResult(DataObjectActionResult):
    """Report one durable PDF receipt without returning a filesystem path."""

    receipt_id: str
    sha256: str
    byte_size: int
    disposition: PdfReceiptDisposition

    def __post_init__(self) -> None:
        if (
            type(self.receipt_id) is not str
            or _RECEIPT_ID.fullmatch(self.receipt_id) is None
        ):
            raise ValueError("receipt_id is not a document receipt identity")
        validate_sha256(self.sha256)
        if (
            type(self.byte_size) is not int
            or not 1 <= self.byte_size <= MAX_PDF_BYTES
        ):
            raise ValueError("byte_size is outside the supported PDF range")
        if type(self.disposition) is not PdfReceiptDisposition:
            raise ValueError("disposition must be a PdfReceiptDisposition")


@dataclass(frozen=True, slots=True, kw_only=True)
class MissingPdfReference(ReferenceDisplayMetadata):
    """Describe one privacy-reduced missing-PDF row."""

    pdf_requirement: PdfRequirement = PdfRequirement.REQUIRED

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.pdf_requirement is not PdfRequirement.REQUIRED:
            raise ValueError(
                "a missing PDF row must have requirement 'required'"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMissingPdfReferencesRequest(DataObjectActionRequest):
    """Select one collection for missing-PDF derivation."""

    collection_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.collection_id, field="collection_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMissingPdfReferencesResult(DataObjectActionResult):
    """Return a bounded missing list and aggregate collection counts."""

    collection_id: str
    source_id: str
    source_revision: str
    required_count: int
    bound_count: int
    not_applicable_count: int
    missing: tuple[MissingPdfReference, ...]

    def __post_init__(self) -> None:
        validate_identifier(self.collection_id, field="collection_id")
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


@dataclass(frozen=True, slots=True, kw_only=True)
class BindPdfToReferenceRequest(DataObjectActionRequest):
    """Select an existing PDF and required collection member explicitly."""

    collection_id: str
    citekey: str
    document_sha256: str

    def __post_init__(self) -> None:
        validate_identifier(self.collection_id, field="collection_id")
        validate_identifier(self.citekey, field="citekey")
        validate_sha256(self.document_sha256, field="document_sha256")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentBinding(DataObjectModel):
    """Identify one immutable neutral reference/document binding."""

    binding_id: str
    citekey: str
    document_sha256: str
    linkage_basis: str

    def __post_init__(self) -> None:
        if (
            type(self.binding_id) is not str
            or _BINDING_ID.fullmatch(self.binding_id) is None
        ):
            raise ValueError("binding_id is not a reference binding identity")
        validate_identifier(self.citekey, field="citekey")
        validate_sha256(self.document_sha256, field="document_sha256")
        if self.linkage_basis not in _BINDING_BASES:
            raise ValueError("linkage_basis is not supported")


@dataclass(frozen=True, slots=True, kw_only=True)
class BindPdfToReferenceResult(DataObjectActionResult):
    """Report the effect of an atomic binding attempt."""

    binding: ReferenceDocumentBinding
    disposition: BindingDisposition

    def __post_init__(self) -> None:
        if type(self.binding) is not ReferenceDocumentBinding:
            raise ValueError("binding must be a ReferenceDocumentBinding")
        if type(self.disposition) is not BindingDisposition:
            raise ValueError("disposition must be a BindingDisposition")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptRecordEffect(DataObjectModel):
    """Report whether durable document and receipt rows were inserted."""

    receipt_id: str
    document_created: bool
    receipt_created: bool

    def __post_init__(self) -> None:
        if (
            type(self.receipt_id) is not str
            or _RECEIPT_ID.fullmatch(self.receipt_id) is None
        ):
            raise ValueError("receipt_id is not a document receipt identity")
        if type(self.document_created) is not bool:
            raise ValueError("document_created must be a bool")
        if type(self.receipt_created) is not bool:
            raise ValueError("receipt_created must be a bool")


class DocumentReferenceRepository(Protocol):
    """Required persistence boundary for the owning operations."""

    def record_reference(self, *, reference: ReferenceRecord) -> None: ...

    def record_collection(self, *, collection: ReferenceCollection) -> None: ...

    def record_membership(
        self, *, membership: ReferenceCollectionMembership
    ) -> None: ...

    def record_pdf_receipt(
        self,
        *,
        document: StoredPdfObject,
        source_link: str | None,
    ) -> ReceiptRecordEffect: ...

    def list_missing_pdf_references(
        self, *, collection_id: str
    ) -> ListMissingPdfReferencesResult: ...

    def bind_pdf_to_reference(
        self, *, request: BindPdfToReferenceRequest
    ) -> BindPdfToReferenceResult: ...


class PdfObjectReceiver(Protocol):
    """Required filesystem boundary for bounded content-addressed receipt."""

    def receive(
        self,
        *,
        stream: BinaryIO,
        declared_byte_size: int | None,
    ) -> StoredPdfObject: ...


@final
class ReceivePdf:
    """Coordinate byte receipt and its immutable source observation."""

    __slots__ = ("_objects", "_repository")

    def __init__(
        self,
        *,
        objects: PdfObjectReceiver,
        repository: DocumentReferenceRepository,
    ) -> None:
        self._objects = objects
        self._repository = repository

    def receive(
        self,
        *,
        request: ReceivePdfRequest,
        stream: BinaryIO,
    ) -> ReceivePdfResult:
        """Receive a bounded stream without binding or changing metadata."""
        document = self._objects.receive(
            stream=stream,
            declared_byte_size=request.declared_byte_size,
        )
        effect = self._repository.record_pdf_receipt(
            document=document,
            source_link=request.source_link,
        )
        if document.created or effect.document_created:
            disposition = PdfReceiptDisposition.RECEIVED
        elif effect.receipt_created:
            disposition = PdfReceiptDisposition.SOURCE_OBSERVATION_ADDED
        else:
            disposition = PdfReceiptDisposition.ALREADY_PRESENT
        return ReceivePdfResult(
            receipt_id=effect.receipt_id,
            sha256=document.sha256,
            byte_size=document.byte_size,
            disposition=disposition,
        )


@final
class ListMissingPdfReferences(
    DataObjectActionizer[
        ListMissingPdfReferencesRequest,
        ListMissingPdfReferencesResult,
    ]
):
    """Derive missing PDFs from membership, requirement, and binding rows."""

    __slots__ = ("_repository",)

    def __init__(self, *, repository: DocumentReferenceRepository) -> None:
        self._repository = repository

    def action(
        self, *, request: ListMissingPdfReferencesRequest
    ) -> ListMissingPdfReferencesResult:
        return self._repository.list_missing_pdf_references(
            collection_id=request.collection_id
        )


@final
class BindPdfToReference(
    DataObjectActionizer[BindPdfToReferenceRequest, BindPdfToReferenceResult]
):
    """Create an explicit one-to-one binding or return an exact retry."""

    __slots__ = ("_repository",)

    def __init__(self, *, repository: DocumentReferenceRepository) -> None:
        self._repository = repository

    def action(
        self, *, request: BindPdfToReferenceRequest
    ) -> BindPdfToReferenceResult:
        return self._repository.bind_pdf_to_reference(request=request)
