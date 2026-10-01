from __future__ import annotations

from dataclasses import dataclass, field, replace

from projectkoios.base import DataObjectModel

from ._contract import (
    CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
    CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY,
    CITATION_DOCUMENT_MAX_PDF_BYTES,
    _CitationDocumentContract,
    stable_id,
    validate_literal_citekey,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentDescriptor(DataObjectModel):
    """Opaque PDF descriptor without bytes, path, rights, or ingestion state."""

    source_document_id: str
    sha256: str
    byte_size: int
    media_type: str = "application/pdf"
    descriptor_id: str = field(init=False)

    def __post_init__(self) -> None:
        _CitationDocumentContract.opaque_id(
            self.source_document_id,
            field_name="source document identity",
        )
        if not _CitationDocumentContract._DIGEST.fullmatch(self.sha256):
            raise ValueError("source document SHA-256 is invalid")
        if (
            type(self.byte_size) is not int
            or not 0 < self.byte_size <= CITATION_DOCUMENT_MAX_PDF_BYTES
        ):
            raise ValueError("source document byte size is invalid")
        if self.media_type != "application/pdf":
            raise ValueError(
                "source document media type must be application/pdf"
            )
        object.__setattr__(
            self,
            "descriptor_id",
            stable_id(
                "citation-source-document-descriptor",
                self.identity_payload(),
            ),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
        }

    def validate_identity(self) -> None:
        if replace(self) != self:
            raise ValueError("source document descriptor does not match replay")

    def record_payload(self) -> dict[str, object]:
        return {
            "source_document_id": self.source_document_id,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "descriptor_id": self.descriptor_id,
        }

    @property
    def content_key(self) -> tuple[str, int]:
        return (self.sha256, self.byte_size)


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentObservation(DataObjectModel):
    """Bounded document availability evidence for one literal key."""

    target_snapshot_id: str
    literal_citekey: str
    coverage_status: str
    source_documents: tuple[CitationSourceDocumentDescriptor, ...]
    inaccessible_evidence_ids: tuple[str, ...]
    evidence_id: str
    observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.target_snapshot_id,
            kind="snapshot",
            field_name="document observation target snapshot",
        )
        validate_literal_citekey(
            self.literal_citekey,
            field_name="document observation key",
        )
        if self.coverage_status not in {"complete", "incomplete"}:
            raise ValueError("document evidence coverage status is invalid")
        if (
            not isinstance(self.source_documents, tuple)
            or len(self.source_documents)
            > CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY
            or any(
                not isinstance(item, CitationSourceDocumentDescriptor)
                for item in self.source_documents
            )
        ):
            raise TypeError("source document descriptors are invalid")
        descriptor_ids = tuple(
            item.descriptor_id for item in self.source_documents
        )
        if descriptor_ids != tuple(sorted(descriptor_ids)) or len(
            descriptor_ids
        ) != len(set(descriptor_ids)):
            raise ValueError("source document descriptors are not canonical")
        source_ids = tuple(
            item.source_document_id for item in self.source_documents
        )
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source document identities contain duplicates")
        if (
            not isinstance(self.inaccessible_evidence_ids, tuple)
            or len(self.inaccessible_evidence_ids)
            > CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY
            or self.inaccessible_evidence_ids
            != tuple(sorted(set(self.inaccessible_evidence_ids)))
        ):
            raise ValueError(
                "inaccessible evidence identities are not canonical"
            )
        for identity in self.inaccessible_evidence_ids:
            _CitationDocumentContract.opaque_id(
                identity,
                field_name="inaccessible evidence identity",
            )
        _CitationDocumentContract.opaque_id(
            self.evidence_id,
            field_name="document observation evidence identity",
        )
        object.__setattr__(
            self,
            "observation_id",
            stable_id(
                "citation-source-document-observation",
                {
                    "target_snapshot_id": self.target_snapshot_id,
                    "literal_citekey": self.literal_citekey,
                    "coverage_status": self.coverage_status,
                    "source_documents": [
                        item.record_payload() for item in self.source_documents
                    ],
                    "inaccessible_evidence_ids": list(
                        self.inaccessible_evidence_ids
                    ),
                    "evidence_id": self.evidence_id,
                },
            ),
        )

    def validate_identity(self) -> None:
        for descriptor in self.source_documents:
            descriptor.validate_identity()
        if replace(self) != self:
            raise ValueError(
                "source document observation does not match replay"
            )
