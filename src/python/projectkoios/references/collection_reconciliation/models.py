from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar, overload

from projectkoios.references.citation_closure import (
    CitationClosure,
)
from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageState,
)
from projectkoios.references.path_safety import (
    PlaceholderObservation,
    RootPreflightEvidence,
    validate_citekey,
)
from projectkoios.references.reconciliation_package import (
    ContentEvidence,
    FrozenCounts,
    ReconciliationPackageManifest,
    pretty_json,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
)

from ._contract import (
    _stable_id,
)

_Value = TypeVar("_Value")


class CollectionReconciliationError(RuntimeError):
    """Raised when collection evidence cannot be reconciled safely."""


class IncompleteReconciliationPublicationError(CollectionReconciliationError):
    """A claimed output directory lacks a verified completion state."""

    code = "reconciliation-publication-incomplete"


@dataclass(frozen=True)
class EvidenceMapping(Mapping[str, _Value]):
    """Immutable parsed values retaining exact input-byte evidence."""

    entries: tuple[tuple[str, _Value], ...]
    input_evidence: tuple[ContentEvidence, ...]
    root_preflights: tuple[RootPreflightEvidence, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(key for key, _ in self.entries)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("evidence mapping keys must be sorted and unique")

    def __getitem__(self, key: str) -> _Value:
        for candidate, value in self.entries:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


class PdfExpectation(StrEnum):
    EXPECTED = "expected"
    REVIEW = "review"
    NOT_APPLICABLE = "not-applicable"


class PdfStatus(StrEnum):
    MANAGED_VERIFIED = "managed-verified"
    MANAGED_PRESENT = "managed-present"
    LOCATED_UNVERIFIED = "located-unverified"
    AMBIGUOUS_MATCHES = "ambiguous-matches"
    ALTERNATE_VERSION_ONLY = "alternate-version-only"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    NOT_YET_SEARCHED = "not-yet-searched"
    SEARCH_INCOMPLETE = "search-incomplete"
    SEARCH_FAILED = "search-failed"
    NOT_LOCATED = "not-located"
    ACCESS_CONTROLLED = "access-controlled"
    FULL_TEXT_NOT_PUBLIC = "full-text-not-public"
    PDF_NOT_APPLICABLE = "pdf-not-applicable"
    PDF_APPLICABILITY_REVIEW = "pdf-applicability-review"


class CitationStatus(StrEnum):
    CITED_DEFINED = "cited-defined"
    DEFINED_UNCITED = "defined-uncited"
    CLOSURE_UNAVAILABLE = "closure-unavailable"


@dataclass(frozen=True)
class CollectionRowEvidence:
    source_bibliographies: tuple[str, ...]
    bibliographic_status: str
    reading_status: str
    observation_id: str | None = None
    source_content_id: str | None = None
    row_index: int | None = None
    parser_name: str | None = None
    parser_version: str | None = None

    def __post_init__(self) -> None:
        provenance = (
            self.observation_id,
            self.source_content_id,
            self.row_index,
            self.parser_name,
            self.parser_version,
        )
        if all(item is None for item in provenance):
            return
        if any(item is None for item in provenance):
            raise ValueError(
                "collection row provenance must be complete or absent"
            )
        if (
            re.fullmatch(
                r"collection-row-observation:sha256:[0-9a-f]{64}",
                str(self.observation_id),
            )
            is None
        ):
            raise ValueError("collection row observation identity is invalid")
        if (
            re.fullmatch(
                r"blob:sha256:[0-9a-f]{64}",
                str(self.source_content_id),
            )
            is None
        ):
            raise ValueError("collection row source identity is invalid")
        if type(self.row_index) is not int or self.row_index < 0:
            raise ValueError("collection row index is invalid")
        if not self.parser_name or not self.parser_version:
            raise ValueError("collection row parser identity is invalid")
        expected = _stable_id(
            "collection-row-observation",
            {
                "source_content_id": self.source_content_id,
                "row_index": self.row_index,
                "parser_name": self.parser_name,
                "parser_version": self.parser_version,
                "source_bibliographies": self.source_bibliographies,
                "bibliographic_status": self.bibliographic_status,
                "reading_status": self.reading_status,
            },
        )
        if self.observation_id != expected:
            raise ValueError("collection row observation identity differs")


@dataclass(frozen=True, init=False)
class ProcessingEvidence:
    ingestion_status: str
    transcript_status: str
    evidence_record_id: str | None
    contract_status: str
    derivation_audit_status: str
    derivation_audit_scope: str
    independently_revalidated: bool

    @classmethod
    def _create(
        cls,
        *,
        ingestion_status: str,
        transcript_status: str,
        evidence_record_id: str | None,
        contract_status: str,
        derivation_audit_status: str,
        derivation_audit_scope: str,
        independently_revalidated: bool,
    ) -> ProcessingEvidence:
        value = object.__new__(cls)
        for field_name, field_value in (
            ("ingestion_status", ingestion_status),
            ("transcript_status", transcript_status),
            ("evidence_record_id", evidence_record_id),
            ("contract_status", contract_status),
            ("derivation_audit_status", derivation_audit_status),
            ("derivation_audit_scope", derivation_audit_scope),
            ("independently_revalidated", independently_revalidated),
        ):
            object.__setattr__(value, field_name, field_value)
        value.__post_init__()
        return value

    @classmethod
    def _from_reference_evidence(
        cls,
        *,
        evidence_record_id: str,
        contract_status: str,
        derivation_audit_status: str,
        derivation_audit_scope: str,
        independently_revalidated: bool,
    ) -> ProcessingEvidence:
        return cls._create(
            ingestion_status="completed-source-bound-reference-evidence",
            transcript_status=(
                "automated-unreviewed-with-recorded-passing-audit"
            ),
            evidence_record_id=evidence_record_id,
            contract_status=contract_status,
            derivation_audit_status=derivation_audit_status,
            derivation_audit_scope=derivation_audit_scope,
            independently_revalidated=independently_revalidated,
        )

    @classmethod
    def not_supplied(cls) -> ProcessingEvidence:
        return cls._create(
            ingestion_status="reference-evidence-not-supplied",
            transcript_status="reference-evidence-not-supplied",
            evidence_record_id=None,
            contract_status="not-supplied",
            derivation_audit_status="not-supplied",
            derivation_audit_scope="not-supplied",
            independently_revalidated=False,
        )

    def __post_init__(self) -> None:
        if self.evidence_record_id is None:
            if (
                self.ingestion_status,
                self.transcript_status,
                self.contract_status,
                self.derivation_audit_status,
                self.derivation_audit_scope,
                self.independently_revalidated,
            ) != (
                "reference-evidence-not-supplied",
                "reference-evidence-not-supplied",
                "not-supplied",
                "not-supplied",
                "not-supplied",
                False,
            ):
                raise ValueError(
                    "processing evidence without a record must be "
                    "explicitly not supplied"
                )
            return
        if (
            re.fullmatch(
                r"reference-evidence-record:sha256:[0-9a-f]{64}",
                self.evidence_record_id,
            )
            is None
        ):
            raise ValueError("processing evidence record identity is invalid")
        expected = (
            "completed-source-bound-reference-evidence",
            "automated-unreviewed-with-recorded-passing-audit",
            "proposed",
            "recorded-passing",
            "recorded_producer_derivation_audit",
            False,
        )
        actual = (
            self.ingestion_status,
            self.transcript_status,
            self.contract_status,
            self.derivation_audit_status,
            self.derivation_audit_scope,
            self.independently_revalidated,
        )
        if actual != expected:
            raise ValueError(
                "processing evidence status contradicts the supported "
                "producer record"
            )


@dataclass(frozen=True)
class ManagedPdf:
    filename: str
    citekey: str
    sha256: str
    byte_size: int
    historically_verified: bool
    discovery_evidence: tuple[str, ...]


@dataclass(frozen=True)
class ManagedPdfScan(Sequence[ManagedPdf]):
    pdfs: tuple[ManagedPdf, ...]
    input_evidence: tuple[ContentEvidence, ...]
    root_preflight: RootPreflightEvidence
    file_observations: tuple[PlaceholderObservation, ...]

    def __post_init__(self) -> None:
        if self.file_observations:
            raise ValueError(
                "complete managed-PDF scans cannot contain skipped "
                "file observations"
            )

    @overload
    def __getitem__(self, index: int) -> ManagedPdf: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[ManagedPdf, ...]: ...

    def __getitem__(
        self, index: int | slice
    ) -> ManagedPdf | tuple[ManagedPdf, ...]:
        return self.pdfs[index]

    def __len__(self) -> int:
        return len(self.pdfs)


@dataclass(frozen=True)
class CollectionReference:
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    entry_type: str
    source_type: str
    full_text_expected: bool | None
    title: str | None
    year: str | None
    doi: str | None
    source_bibliographies: tuple[str, ...]
    metadata_verification_status: str
    reading_status: str
    reading_decision_status: str
    citation_status: CitationStatus
    pdf_expectation: PdfExpectation
    pdf_status: PdfStatus
    managed_pdf: str | None
    sha256: str | None
    byte_size: int | None
    discovery_evidence: tuple[str, ...]
    duplicate_citekeys: tuple[str, ...]
    acquisition_status: str
    access_status: str
    rights_status: str
    ingestion_status: str
    transcript_status: str
    state_projection_id: str
    state_discrepancy_fields: tuple[str, ...]
    next_lawful_action: str

    def __post_init__(self) -> None:
        validate_citekey(
            self.proposed_citekey,
            field="proposed citekey",
        )
        if self.identity_status != "unaccepted-candidate":
            raise ValueError(
                "collection reference cannot claim accepted identity"
            )
        if self.citekey_status != "proposed-noncanonical":
            raise ValueError(
                "collection reference citekey must be noncanonical"
            )


@dataclass(frozen=True)
class ExtraPdf:
    filename: str
    proposed_citekey: str
    sha256: str
    byte_size: int
    duplicate_citekeys: tuple[str, ...]
    access_status: str
    rights_status: str
    ingestion_status: str
    transcript_status: str


@dataclass(frozen=True)
class CollectionManifest:
    schema_version: int
    processor_version: str
    collection_id: str
    asserted_source_revision: str
    bibliography_sha256: str
    coverage_observation_id: str | None
    coverage_state: CoverageState | None
    ambiguity_evaluation: AmbiguityEvaluation
    coverage: tuple[str, ...]
    state_projections: tuple[ReferenceStateProjection, ...]
    references: tuple[CollectionReference, ...]
    extra_pdfs: tuple[ExtraPdf, ...]
    counts: FrozenCounts
    manifest_id: str

    def to_json(self) -> str:
        return pretty_json(self)


@dataclass(frozen=True)
class ReconciliationOutputs:
    manifest: CollectionManifest
    citation_closure: CitationClosure | None
    package_manifest: ReconciliationPackageManifest
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class PublicationResult:
    status: str
    output_directory: Path
    package_id: str
