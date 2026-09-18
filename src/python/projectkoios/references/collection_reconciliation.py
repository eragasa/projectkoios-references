from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar, cast, overload
from urllib.parse import urlparse

from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    PathSafetyError,
    read_path_bytes,
    validate_citekey,
    validate_relative_path,
)
from projectkoios.references.reconciliation_package import (
    PACKAGE_MANIFEST_FILENAME,
    ContentEvidence,
    FrozenCounts,
    LoadedReconciliationPackage,
    ReconciliationPackageError,
    ReconciliationPackageManifest,
    SoftwareIdentity,
    VerifiedSourceTree,
    canonical_json_bytes,
    load_reconciliation_package,
    parse_package_files,
    pretty_json,
)

_SCHEMA_VERSION = 2
_PROCESSOR_VERSION = "0.6.0"
_CITATION_PARSER_VERSION = "1"
_COLLECTION_ROWS_PARSER_VERSION = "1"
_SOURCE_DISCOVERY_PARSER_VERSION = "1"
_REFERENCE_EVIDENCE_CONSUMER_VERSION = "1"
_MAX_RECORDS = 10_000
_MAX_INPUT_JSON_BYTES = 10_000_000
_MAX_COLLECTION_ROWS_BYTES = 50_000_000
_MAX_TEX_FILES = 10_000
_MAX_TEX_BYTES = 50_000_000
_MAX_PDF_BYTES = 4_000_000_000
_CITATION = re.compile(
    r"\\(?:[A-Za-z]*cite[A-Za-z]*|nocite)\s*"
    r"(?:\[[^\]]*\]\s*){0,2}\{([^{}]+)\}",
    re.MULTILINE,
)
_EXPECTED_PDF_TYPES = frozenset(
    {
        "article",
        "book",
        "booklet",
        "conference",
        "inbook",
        "incollection",
        "inproceedings",
        "mastersthesis",
        "phdthesis",
        "proceedings",
        "techreport",
        "unpublished",
    }
)


class CollectionReconciliationError(RuntimeError):
    """Raised when collection evidence cannot be reconciled safely."""


_Value = TypeVar("_Value")


@dataclass(frozen=True)
class EvidenceMapping(Mapping[str, _Value]):
    """Immutable parsed values retaining exact input-byte evidence."""

    entries: tuple[tuple[str, _Value], ...]
    input_evidence: tuple[ContentEvidence, ...]

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
class CitationUse:
    citekey: str
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class CitationClosure:
    schema_version: int
    asserted_source_revision: str
    bibliography_keys: tuple[str, ...]
    explicit_uses: tuple[CitationUse, ...]
    cited_and_defined: tuple[str, ...]
    cited_but_undefined: tuple[str, ...]
    defined_but_uncited: tuple[str, ...]
    nocite_all: bool
    source_files: tuple[str, ...]
    source_file_evidence: tuple[ContentEvidence, ...]
    closure_id: str
    verified_source_tree: VerifiedSourceTree | None = field(
        default=None,
        init=False,
    )

    def to_json(self) -> str:
        return pretty_json(self)


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
    citation_status: CitationStatus
    pdf_expectation: PdfExpectation
    pdf_status: PdfStatus
    managed_pdf: str | None
    sha256: str | None
    byte_size: int | None
    discovery_evidence: tuple[str, ...]
    duplicate_citekeys: tuple[str, ...]
    access_status: str
    rights_status: str
    ingestion_status: str
    transcript_status: str
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


def load_collection_rows(
    path: Path,
) -> EvidenceMapping[CollectionRowEvidence]:
    content = read_path_bytes(
        path,
        label="collection rows",
        max_bytes=_MAX_COLLECTION_ROWS_BYTES,
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CollectionReconciliationError(
            "collection rows are not UTF-8"
        ) from error
    rows = tuple(csv.DictReader(io.StringIO(text, newline="")))
    if len(rows) > _MAX_RECORDS:
        raise CollectionReconciliationError("collection rows exceed hard limit")
    result: dict[str, CollectionRowEvidence] = {}
    for row in rows:
        citekey = (row.get("citekey") or "").strip()
        if not citekey:
            raise CollectionReconciliationError(
                "collection row has an empty citekey"
            )
        try:
            validate_citekey(citekey)
        except PathSafetyError as error:
            raise CollectionReconciliationError(
                f"collection row has an unsafe citekey: {citekey}"
            ) from error
        if citekey in result:
            raise CollectionReconciliationError(
                f"duplicate collection row: {citekey}"
            )
        sources = tuple(
            item
            for item in (row.get("source_bibliographies") or "").split(";")
            if item
        )
        result[citekey] = CollectionRowEvidence(
            source_bibliographies=sources,
            bibliographic_status=(
                row.get("bibliographic_status") or "unrecorded"
            ),
            reading_status=row.get("reading_status") or "unrecorded",
        )
    return EvidenceMapping(
        entries=tuple(sorted(result.items())),
        input_evidence=(
            ContentEvidence.from_bytes(
                role="collection-rows",
                filename="inputs/collection-rows.csv",
                content=content,
            ),
        ),
    )


def scan_managed_pdfs(
    directory: Path,
    *,
    source_discovery: Path | None = None,
) -> ManagedPdfScan:
    try:
        root = AuthorizedRoot.existing(directory, label="managed PDF root")
        relative_files = root.iter_files(suffix=".pdf", recursive=False)
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    historical, discovery_evidence = _load_source_discovery(source_discovery)
    pdfs: list[ManagedPdf] = []
    asset_evidence: list[ContentEvidence] = []
    for relative in relative_files:
        try:
            citekey = validate_citekey(Path(relative.name).stem)
            content = root.read_bytes(relative, max_bytes=_MAX_PDF_BYTES)
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        byte_size = len(content)
        if byte_size <= 0:
            raise CollectionReconciliationError(
                f"managed PDF size is outside bounds: {relative.name}"
            )
        digest = _hash_pdf(content, filename=relative.name)
        asset_evidence.append(
            ContentEvidence(
                role="managed-asset",
                filename=f"inputs/managed-assets/{relative.name}",
                byte_size=byte_size,
                sha256=digest,
            )
        )
        discovery = historical.get(citekey)
        if discovery is not None and discovery[0] == digest:
            verified = True
            evidence = discovery[1]
        else:
            verified = False
            evidence = ()
        pdfs.append(
            ManagedPdf(
                filename=relative.name,
                citekey=citekey,
                sha256=digest,
                byte_size=byte_size,
                historically_verified=verified,
                discovery_evidence=evidence,
            )
        )
    return ManagedPdfScan(
        pdfs=tuple(pdfs),
        input_evidence=tuple(
            sorted(
                (*discovery_evidence, *asset_evidence),
                key=_content_evidence_key,
            )
        ),
    )


def build_citation_closure(
    manuscript_root: Path,
    *,
    bibliography_keys: tuple[str, ...],
    source_revision: str,
) -> CitationClosure:
    try:
        root = AuthorizedRoot.existing(
            manuscript_root,
            label="manuscript root",
        )
        source_files = root.iter_files(suffix=".tex", recursive=True)
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    if len(source_files) > _MAX_TEX_FILES:
        raise CollectionReconciliationError("TeX source count exceeds limit")

    uses: dict[str, set[str]] = defaultdict(set)
    nocite_all = False
    relative_files: list[str] = []
    source_file_evidence: list[ContentEvidence] = []
    total_bytes = 0
    for relative_path in source_files:
        try:
            content = root.read_bytes(
                relative_path,
                max_bytes=_MAX_TEX_BYTES,
            )
            text = content.decode("utf-8")
        except (PathSafetyError, UnicodeDecodeError) as error:
            raise CollectionReconciliationError(
                f"cannot safely read TeX source: {relative_path}"
            ) from error
        total_bytes += len(content)
        if total_bytes > _MAX_TEX_BYTES:
            raise CollectionReconciliationError("TeX source bytes exceed limit")
        relative = relative_path.as_posix()
        relative_files.append(relative)
        source_file_evidence.append(
            ContentEvidence.from_bytes(
                role="citation-source",
                filename=f"inputs/citation-source/{relative}",
                content=content,
            )
        )
        uncommented = "\n".join(
            _strip_latex_comment(line) for line in text.splitlines()
        )
        for match in _CITATION.finditer(uncommented):
            for raw_key in match.group(1).split(","):
                key = raw_key.strip()
                if not key:
                    continue
                if key == "*":
                    nocite_all = True
                    continue
                try:
                    validate_citekey(key)
                except PathSafetyError:
                    continue
                uses[key].add(relative)

    try:
        bibliography = {
            validate_citekey(key, field="bibliography citekey")
            for key in bibliography_keys
        }
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    cited = set(uses)
    verified_source_tree = _verify_source_tree(
        root.path,
        asserted_revision=source_revision,
    )
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "asserted_source_revision": source_revision,
        "verified_source_tree": verified_source_tree,
        "bibliography_keys": sorted(bibliography),
        "explicit_uses": [
            {
                "citekey": key,
                "source_files": sorted(uses[key]),
            }
            for key in sorted(uses)
        ],
        "cited_and_defined": sorted(cited & bibliography),
        "cited_but_undefined": sorted(cited - bibliography),
        "defined_but_uncited": sorted(bibliography - cited),
        "nocite_all": nocite_all,
        "source_files": sorted(relative_files),
        "source_file_evidence": sorted(
            source_file_evidence,
            key=_content_evidence_key,
        ),
    }
    closure_id = _stable_id("citation-closure", payload)
    closure = CitationClosure(
        schema_version=_SCHEMA_VERSION,
        asserted_source_revision=source_revision,
        bibliography_keys=tuple(payload["bibliography_keys"]),
        explicit_uses=tuple(
            CitationUse(
                citekey=item["citekey"],
                source_files=tuple(item["source_files"]),
            )
            for item in payload["explicit_uses"]
        ),
        cited_and_defined=tuple(payload["cited_and_defined"]),
        cited_but_undefined=tuple(payload["cited_but_undefined"]),
        defined_but_uncited=tuple(payload["defined_but_uncited"]),
        nocite_all=nocite_all,
        source_files=tuple(payload["source_files"]),
        source_file_evidence=tuple(
            cast(list[ContentEvidence], payload["source_file_evidence"])
        ),
        closure_id=closure_id,
    )
    object.__setattr__(
        closure,
        "verified_source_tree",
        verified_source_tree,
    )
    return closure


def reconcile_collection(
    records: tuple[ReferenceCandidate, ...],
    *,
    bibliography_bytes: bytes,
    collection_id: str,
    source_revision: str,
    collection_rows: Mapping[str, CollectionRowEvidence],
    managed_pdfs: Sequence[ManagedPdf],
    citation_closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None = None,
    coverage_observation_bytes: bytes | None = None,
    processing_evidence: Mapping[str, ProcessingEvidence] | None = None,
    bibliography_parser: str = "caller-supplied-records",
) -> ReconciliationOutputs:
    if not collection_id or not source_revision:
        raise CollectionReconciliationError(
            "collection and asserted source revision must be non-empty"
        )
    if not bibliography_parser:
        raise CollectionReconciliationError(
            "bibliography parser identity must be non-empty"
        )
    if coverage_observation_bytes is not None:
        if coverage_observation is None:
            raise CollectionReconciliationError(
                "coverage bytes were supplied without an observation"
            )
        try:
            parsed_coverage = CoverageObservation.from_json(
                coverage_observation_bytes.decode("utf-8")
            )
        except (UnicodeDecodeError, ValueError) as error:
            raise CollectionReconciliationError(
                "coverage observation bytes are invalid"
            ) from error
        if parsed_coverage != coverage_observation:
            raise CollectionReconciliationError(
                "coverage observation bytes differ from parsed evidence"
            )
    if not records or len(records) > _MAX_RECORDS:
        raise CollectionReconciliationError(
            "bibliography record count is outside bounds"
        )
    processing_supplied = processing_evidence is not None
    processing_by_citekey = processing_evidence or {}
    coverage_by_citekey = (
        coverage_observation.by_citekey()
        if coverage_observation is not None
        else {}
    )
    ordered_records = tuple(
        sorted(records, key=lambda item: item.proposed_citekey)
    )
    try:
        citekeys = tuple(
            validate_citekey(record.proposed_citekey)
            for record in ordered_records
        )
        for managed_pdf in managed_pdfs:
            validate_citekey(
                managed_pdf.citekey,
                field="managed PDF citekey",
            )
        for citekey in processing_by_citekey:
            validate_citekey(
                citekey,
                field="processing-evidence citekey",
            )
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    if len(citekeys) != len(set(citekeys)):
        raise CollectionReconciliationError(
            "bibliography contains duplicate citekeys"
        )
    if coverage_observation is not None:
        if coverage_observation.asserted_source_revision != source_revision:
            raise CollectionReconciliationError(
                "coverage observation source assertion differs"
            )
        extra_coverage = sorted(set(coverage_by_citekey) - set(citekeys))
        if extra_coverage:
            raise CollectionReconciliationError(
                "coverage observation has references outside the "
                f"bibliography: {extra_coverage}"
            )
        if coverage_observation.state is CoverageState.COMPLETE and set(
            coverage_by_citekey
        ) != set(citekeys):
            missing_coverage = sorted(set(citekeys) - set(coverage_by_citekey))
            raise CollectionReconciliationError(
                "complete coverage omits bibliography references: "
                f"{missing_coverage}"
            )
    if set(collection_rows) != set(citekeys):
        missing = sorted(set(citekeys) - set(collection_rows))
        extra = sorted(set(collection_rows) - set(citekeys))
        raise CollectionReconciliationError(
            f"collection row coverage differs: missing={missing}, extra={extra}"
        )
    if citation_closure is not None and (
        citation_closure.asserted_source_revision != source_revision
        or set(citation_closure.bibliography_keys) != set(citekeys)
    ):
        raise CollectionReconciliationError(
            "citation closure does not match bibliography source"
        )

    by_citekey = {item.citekey: item for item in managed_pdfs}
    if len(by_citekey) != len(managed_pdfs):
        raise CollectionReconciliationError(
            "managed PDF directory has duplicate citekey stems"
        )
    unmatched_processing = sorted(set(processing_by_citekey) - set(by_citekey))
    if unmatched_processing:
        raise CollectionReconciliationError(
            "processing evidence has no matching managed PDF: "
            f"{unmatched_processing}"
        )
    if any(
        not isinstance(item, ProcessingEvidence)
        or item.evidence_record_id is None
        for item in processing_by_citekey.values()
    ):
        raise CollectionReconciliationError(
            "supplied processing evidence is not source-bound producer evidence"
        )
    by_digest: dict[str, list[str]] = defaultdict(list)
    for managed_pdf in managed_pdfs:
        by_digest[managed_pdf.sha256].append(managed_pdf.citekey)

    cited = (
        set(citation_closure.cited_and_defined)
        if citation_closure is not None
        else set()
    )
    references: list[CollectionReference] = []
    for record in ordered_records:
        evidence = collection_rows[record.proposed_citekey]
        matched_pdf = by_citekey.get(record.proposed_citekey)
        expectation = _pdf_expectation(record)
        processing = processing_by_citekey.get(
            record.proposed_citekey,
            ProcessingEvidence.not_supplied(),
        )
        coverage_item = coverage_by_citekey.get(record.proposed_citekey)
        status, next_action = _classify_pdf_status(
            matched_pdf=matched_pdf,
            expectation=expectation,
            observation=coverage_observation,
            evidence=coverage_item,
        )
        duplicate_citekeys = (
            tuple(
                sorted(
                    key
                    for key in by_digest[matched_pdf.sha256]
                    if key != record.proposed_citekey
                )
            )
            if matched_pdf is not None
            else ()
        )
        references.append(
            CollectionReference(
                proposed_citekey=record.proposed_citekey,
                identity_status=record.lifecycle_status,
                citekey_status=record.citekey_status,
                entry_type=record.entry_type,
                source_type=_source_type(record),
                full_text_expected=_full_text_expected(expectation),
                title=record.title,
                year=record.year,
                doi=record.doi,
                source_bibliographies=evidence.source_bibliographies,
                metadata_verification_status=evidence.bibliographic_status,
                reading_status=evidence.reading_status,
                citation_status=(
                    CitationStatus.CLOSURE_UNAVAILABLE
                    if citation_closure is None
                    else (
                        CitationStatus.CITED_DEFINED
                        if record.proposed_citekey in cited
                        else CitationStatus.DEFINED_UNCITED
                    )
                ),
                pdf_expectation=expectation,
                pdf_status=status,
                managed_pdf=(
                    matched_pdf.filename if matched_pdf is not None else None
                ),
                sha256=(
                    matched_pdf.sha256 if matched_pdf is not None else None
                ),
                byte_size=(
                    matched_pdf.byte_size if matched_pdf is not None else None
                ),
                discovery_evidence=(
                    matched_pdf.discovery_evidence
                    if matched_pdf is not None
                    else _coverage_evidence(coverage_item)
                ),
                duplicate_citekeys=duplicate_citekeys,
                access_status=_access_status(
                    matched_pdf=matched_pdf,
                    evidence=coverage_item,
                ),
                rights_status="not-assessed",
                ingestion_status=processing.ingestion_status,
                transcript_status=processing.transcript_status,
                next_lawful_action=next_action,
            )
        )

    seed = set(citekeys)
    extras = tuple(
        ExtraPdf(
            filename=pdf.filename,
            proposed_citekey=pdf.citekey,
            sha256=pdf.sha256,
            byte_size=pdf.byte_size,
            duplicate_citekeys=tuple(
                sorted(
                    key for key in by_digest[pdf.sha256] if key != pdf.citekey
                )
            ),
            access_status="managed-local-access",
            rights_status="not-assessed",
            ingestion_status=processing_by_citekey.get(
                pdf.citekey,
                ProcessingEvidence.not_supplied(),
            ).ingestion_status,
            transcript_status=processing_by_citekey.get(
                pdf.citekey,
                ProcessingEvidence.not_supplied(),
            ).transcript_status,
        )
        for pdf in managed_pdfs
        if pdf.citekey not in seed
    )
    counts = FrozenCounts(_counts(tuple(references), extras, citation_closure))
    coverage = _coverage_claims(
        coverage_observation=coverage_observation,
        processing_supplied=processing_supplied,
        citation_closure_supplied=citation_closure is not None,
    )
    bibliography_sha256 = hashlib.sha256(bibliography_bytes).hexdigest()
    manifest_payload = {
        "schema_version": _SCHEMA_VERSION,
        "processor_version": _PROCESSOR_VERSION,
        "collection_id": collection_id,
        "asserted_source_revision": source_revision,
        "bibliography_sha256": bibliography_sha256,
        "coverage_observation_id": (
            coverage_observation.coverage_id
            if coverage_observation is not None
            else None
        ),
        "coverage_state": (
            coverage_observation.state
            if coverage_observation is not None
            else None
        ),
        "ambiguity_evaluation": (
            coverage_observation.ambiguity_evaluation
            if coverage_observation is not None
            else AmbiguityEvaluation.NOT_EVALUATED
        ),
        "coverage": list(coverage),
        "references": [asdict(record) for record in references],
        "extra_pdfs": [asdict(extra) for extra in extras],
        "counts": counts,
    }
    manifest = CollectionManifest(
        schema_version=_SCHEMA_VERSION,
        processor_version=_PROCESSOR_VERSION,
        collection_id=collection_id,
        asserted_source_revision=source_revision,
        bibliography_sha256=bibliography_sha256,
        coverage_observation_id=(
            coverage_observation.coverage_id
            if coverage_observation is not None
            else None
        ),
        coverage_state=(
            coverage_observation.state
            if coverage_observation is not None
            else None
        ),
        ambiguity_evaluation=(
            coverage_observation.ambiguity_evaluation
            if coverage_observation is not None
            else AmbiguityEvaluation.NOT_EVALUATED
        ),
        coverage=coverage,
        references=tuple(references),
        extra_pdfs=extras,
        counts=counts,
        manifest_id=_stable_id("collection-manifest", manifest_payload),
    )
    rendered = _render_outputs(
        manifest,
        citation_closure,
        coverage_observation,
    )
    inputs = _bound_input_evidence(
        bibliography_bytes=bibliography_bytes,
        collection_rows=collection_rows,
        managed_pdfs=managed_pdfs,
        citation_closure=citation_closure,
        coverage_observation=coverage_observation,
        coverage_observation_bytes=coverage_observation_bytes,
        processing_evidence=processing_evidence,
    )
    package_manifest = ReconciliationPackageManifest.create(
        collection_id=collection_id,
        asserted_source_revision=source_revision,
        verified_source_tree=(
            citation_closure.verified_source_tree
            if citation_closure is not None
            else None
        ),
        components=(
            SoftwareIdentity(
                name="collection-reconciliation",
                version=_PROCESSOR_VERSION,
            ),
            SoftwareIdentity(
                name="collection-rows-parser",
                version=_COLLECTION_ROWS_PARSER_VERSION,
            ),
            SoftwareIdentity(
                name="source-discovery-parser",
                version=_SOURCE_DISCOVERY_PARSER_VERSION,
            ),
            SoftwareIdentity(
                name="ingestion-reference-evidence-consumer",
                version=_REFERENCE_EVIDENCE_CONSUMER_VERSION,
            ),
            SoftwareIdentity(
                name="latex-citation-parser",
                version=_CITATION_PARSER_VERSION,
            ),
            SoftwareIdentity(
                name="bibliography-parser",
                version=bibliography_parser,
            ),
        ),
        inputs=inputs,
        output_files=rendered,
    )
    rendered[PACKAGE_MANIFEST_FILENAME] = package_manifest.to_json().encode(
        "utf-8"
    )
    files = tuple(sorted(rendered.items()))
    try:
        parse_package_files(dict(files))
    except ReconciliationPackageError as error:
        raise CollectionReconciliationError(str(error)) from error
    return ReconciliationOutputs(
        manifest=manifest,
        citation_closure=citation_closure,
        package_manifest=package_manifest,
        files=files,
    )


def publish_reconciliation(
    outputs: ReconciliationOutputs,
    *,
    output_directory: Path,
) -> PublicationResult:
    expected = dict(outputs.files)
    try:
        parsed = parse_package_files(expected)
    except ReconciliationPackageError as error:
        raise CollectionReconciliationError(str(error)) from error
    if parsed.manifest != outputs.package_manifest:
        raise CollectionReconciliationError(
            "in-memory package manifest differs from rendered bytes"
        )
    try:
        parent = AuthorizedRoot.create(
            output_directory.parent,
            label="reconciliation output parent",
        )
        output_name = validate_relative_path(
            output_directory.name,
            field="output directory name",
        )
        output_state = parent.state(output_name)
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    if output_state == "regular":
        raise CollectionReconciliationError(
            "reconciliation output path is not a directory"
        )
    if output_state == "directory":
        try:
            existing = AuthorizedRoot.existing(
                parent.child_path(output_name),
                label="reconciliation output directory",
            )
            actual_names = {
                path.name
                for path in existing.iter_files(
                    suffix="",
                    recursive=False,
                    reject_directories=True,
                )
            }
            if actual_names != set(expected):
                raise CollectionReconciliationError(
                    "existing reconciliation output is incomplete or unexpected"
                )
            for name, content in expected.items():
                if existing.read_bytes(name) != content:
                    raise CollectionReconciliationError(
                        "existing reconciliation output differs"
                    )
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        return PublicationResult(
            status="unchanged",
            output_directory=parent.child_path(output_name),
            package_id=outputs.package_manifest.package_id,
        )

    temporary_name = f".{output_name.name}.{secrets.token_hex(12)}.temporary"
    try:
        temporary = parent.create_directory(temporary_name)
        for name, content in expected.items():
            temporary.write_bytes(name, content, replace=False)
        published = parent.rename_child(temporary_name, output_name)
    except BaseException:
        temporary_path = parent.child_path(temporary_name)
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise
    return PublicationResult(
        status="created",
        output_directory=published,
        package_id=outputs.package_manifest.package_id,
    )


def parse_reconciliation_package(
    text: str,
) -> ReconciliationPackageManifest:
    try:
        return ReconciliationPackageManifest.from_json(text)
    except ValueError as error:
        raise CollectionReconciliationError(str(error)) from error


def verify_reconciliation_package(
    directory: Path,
    *,
    expected_package_id: str | None = None,
) -> LoadedReconciliationPackage:
    try:
        loaded = load_reconciliation_package(directory)
    except ReconciliationPackageError as error:
        raise CollectionReconciliationError(str(error)) from error
    if (
        expected_package_id is not None
        and loaded.manifest.package_id != expected_package_id
    ):
        raise CollectionReconciliationError(
            "reconciliation package identity differs from expected identity"
        )
    return loaded


def replay_reconciliation(
    outputs: ReconciliationOutputs,
    *,
    output_directory: Path,
) -> PublicationResult:
    """Replay deterministic bytes through immutable publication semantics."""
    return publish_reconciliation(outputs, output_directory=output_directory)


def _bound_input_evidence(
    *,
    bibliography_bytes: bytes,
    collection_rows: Mapping[str, CollectionRowEvidence],
    managed_pdfs: Sequence[ManagedPdf],
    citation_closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None,
    coverage_observation_bytes: bytes | None,
    processing_evidence: Mapping[str, ProcessingEvidence] | None,
) -> tuple[ContentEvidence, ...]:
    evidence = [
        ContentEvidence.from_bytes(
            role="bibliography",
            filename="inputs/bibliography.bib",
            content=bibliography_bytes,
        )
    ]
    evidence.extend(_retained_input_evidence(collection_rows))
    if not _retained_input_evidence(collection_rows):
        evidence.append(
            ContentEvidence.from_bytes(
                role="collection-rows-normalized",
                filename="inputs/collection-rows.normalized.json",
                content=canonical_json_bytes(dict(collection_rows)),
            )
        )
    retained_assets = _retained_input_evidence(managed_pdfs)
    evidence.extend(retained_assets)
    if not retained_assets:
        evidence.extend(
            ContentEvidence(
                role="managed-asset",
                filename=f"inputs/managed-assets/{item.filename}",
                byte_size=item.byte_size,
                sha256=item.sha256,
            )
            for item in managed_pdfs
        )
    if citation_closure is not None:
        evidence.extend(citation_closure.source_file_evidence)
        evidence.append(
            ContentEvidence.from_bytes(
                role="citation-closure",
                filename="inputs/citation-closure.json",
                content=citation_closure.to_json().encode("utf-8"),
            )
        )
    if coverage_observation is not None:
        content = (
            coverage_observation_bytes
            if coverage_observation_bytes is not None
            else coverage_observation.to_json().encode("utf-8")
        )
        evidence.append(
            ContentEvidence.from_bytes(
                role="coverage-observation",
                filename="inputs/coverage-observation.json",
                content=content,
            )
        )
    if processing_evidence is not None:
        retained_processing = _retained_input_evidence(processing_evidence)
        evidence.extend(retained_processing)
        if not retained_processing:
            evidence.append(
                ContentEvidence.from_bytes(
                    role="processing-observation",
                    filename="inputs/processing-observation.json",
                    content=canonical_json_bytes(dict(processing_evidence)),
                )
            )
    normalized = canonical_json_bytes(
        {
            "collection_rows": dict(collection_rows),
            "managed_pdfs": tuple(managed_pdfs),
            "coverage_observation": coverage_observation,
            "processing_evidence": (
                None
                if processing_evidence is None
                else dict(processing_evidence)
            ),
        }
    )
    evidence.append(
        ContentEvidence.from_bytes(
            role="normalized-reconciliation-input",
            filename="inputs/reconciliation-input.normalized.json",
            content=normalized,
        )
    )
    ordered = tuple(sorted(evidence, key=_content_evidence_key))
    filenames = tuple(item.filename for item in ordered)
    if len(filenames) != len(set(filenames)):
        raise CollectionReconciliationError(
            "bound input evidence contains duplicate filenames"
        )
    return ordered


def _retained_input_evidence(value: object) -> tuple[ContentEvidence, ...]:
    retained = getattr(value, "input_evidence", ())
    if not isinstance(retained, tuple) or any(
        not isinstance(item, ContentEvidence) for item in retained
    ):
        raise CollectionReconciliationError(
            "retained input evidence has an invalid representation"
        )
    return retained


def _content_evidence_key(
    value: ContentEvidence,
) -> tuple[str, str, int, str]:
    return (value.role, value.filename, value.byte_size, value.sha256)


def _verify_source_tree(
    source_root: Path,
    *,
    asserted_revision: str,
) -> VerifiedSourceTree | None:
    if re.fullmatch(r"[0-9a-f]{40,64}", asserted_revision) is None:
        return None

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(source_root), *arguments),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return completed.stdout.strip()

    try:
        repository_root = Path(git("rev-parse", "--show-toplevel"))
        source_root.resolve(strict=True).relative_to(
            repository_root.resolve(strict=True)
        )
        head = git("rev-parse", "HEAD")
        if head != asserted_revision:
            return None
        if git("status", "--porcelain=v1", "--untracked-files=all"):
            return None
        tree_id = git("rev-parse", "HEAD^{tree}")
    except (
        FileNotFoundError,
        subprocess.SubprocessError,
        TimeoutError,
        ValueError,
    ):
        return None
    return VerifiedSourceTree(
        commit_id=head,
        tree_id=tree_id,
        verification_method="git-clean-head",
    )


def _load_source_discovery(
    path: Path | None,
) -> tuple[
    dict[str, tuple[str, tuple[str, ...]]],
    tuple[ContentEvidence, ...],
]:
    if path is None:
        return {}, ()
    content = read_path_bytes(
        path,
        label="source-discovery document",
        max_bytes=_MAX_INPUT_JSON_BYTES,
    )
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionReconciliationError(
            "source-discovery document is invalid"
        ) from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CollectionReconciliationError(
            "unsupported source-discovery document"
        )
    matches = data.get("matches")
    if not isinstance(matches, list) or len(matches) > _MAX_RECORDS:
        raise CollectionReconciliationError(
            "source-discovery matches are invalid or unbounded"
        )
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for item in matches:
        if not isinstance(item, dict):
            raise CollectionReconciliationError(
                "source-discovery match must be an object"
            )
        citekey = item.get("citekey")
        digest = item.get("sha256")
        basis = item.get("match_basis")
        if (
            not isinstance(citekey, str)
            or not citekey
            or not isinstance(digest, str)
            or not digest
            or not isinstance(basis, str)
            or not basis
        ):
            raise CollectionReconciliationError(
                "source-discovery match identity is incomplete"
            )
        try:
            validate_citekey(citekey, field="source-discovery citekey")
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        if citekey in result:
            raise CollectionReconciliationError(
                f"duplicate source-discovery citekey: {citekey}"
            )
        result[citekey] = (digest, (basis,))
    return result, (
        ContentEvidence.from_bytes(
            role="source-discovery",
            filename="inputs/source-discovery.json",
            content=content,
        ),
    )


def _hash_pdf(content: bytes, *, filename: str) -> str:
    if not content.startswith(b"%PDF-"):
        raise CollectionReconciliationError(
            f"managed file lacks PDF header: {filename}"
        )
    return hashlib.sha256(content).hexdigest()


def _strip_latex_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        preceding = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            preceding += 1
            cursor -= 1
        if preceding % 2 == 0:
            return line[:index]
    return line


def _classify_pdf_status(
    *,
    matched_pdf: ManagedPdf | None,
    expectation: PdfExpectation,
    observation: CoverageObservation | None,
    evidence: ReferenceCoverage | None,
) -> tuple[PdfStatus, str]:
    if matched_pdf is not None:
        return (
            (
                PdfStatus.MANAGED_VERIFIED
                if matched_pdf.historically_verified
                else PdfStatus.MANAGED_PRESENT
            ),
            (
                "verify-bibliographic-metadata-and-rights"
                if matched_pdf.historically_verified
                else "review-pdf-identity-rights-and-record-acquisition"
            ),
        )
    if expectation is PdfExpectation.NOT_APPLICABLE:
        if evidence is not None and (
            evidence.candidates
            or evidence.access_state is not CoverageAccessState.NONE
        ):
            return (
                PdfStatus.PDF_APPLICABILITY_REVIEW,
                "resolve-source-type-and-pdf-applicability-conflict",
            )
        return (
            PdfStatus.PDF_NOT_APPLICABLE,
            "verify-non-pdf-source-locator",
        )
    if expectation is PdfExpectation.REVIEW:
        return (
            PdfStatus.PDF_APPLICABILITY_REVIEW,
            "decide-whether-a-pdf-is-applicable",
        )
    if evidence is None or observation is None:
        return (
            PdfStatus.NOT_YET_SEARCHED,
            "supply-typed-coverage-or-search-authorized-roots",
        )
    if evidence.access_state is CoverageAccessState.CLOUD_PLACEHOLDER:
        return (
            PdfStatus.CLOUD_PLACEHOLDER,
            "request-explicit-placeholder-hydration-authorization",
        )
    if evidence.access_state is CoverageAccessState.ACCESS_CONTROLLED:
        return (
            PdfStatus.ACCESS_CONTROLLED,
            "record-lawful-access-path-without-bypassing-controls",
        )
    if evidence.access_state is CoverageAccessState.FULL_TEXT_NOT_PUBLIC:
        return (
            PdfStatus.FULL_TEXT_NOT_PUBLIC,
            "record-public-metadata-and-private-access-limits",
        )
    if evidence.candidates:
        if evidence.competing_content_count > 1:
            return (
                PdfStatus.AMBIGUOUS_MATCHES,
                "review-competing-candidate-identities",
            )
        if evidence.competing_content_count == 1:
            return (
                PdfStatus.LOCATED_UNVERIFIED,
                "verify-candidate-identity-rights-and-version",
            )
        if evidence.alternate_content_count:
            return (
                PdfStatus.ALTERNATE_VERSION_ONLY,
                "review-alternate-version-identity-and-rights",
            )
        raise CollectionReconciliationError(
            "coverage candidates have no classifiable content identity"
        )
    if not evidence.no_match:
        raise CollectionReconciliationError(
            "coverage evidence has no classifiable outcome"
        )
    if observation.state is CoverageState.COMPLETE:
        return (
            PdfStatus.NOT_LOCATED,
            "record-completed-coverage-or-authorize-new-roots",
        )
    if observation.state is CoverageState.INCOMPLETE:
        return (
            PdfStatus.SEARCH_INCOMPLETE,
            "complete-or-supersede-the-bounded-search",
        )
    if observation.state is CoverageState.FAILED:
        return (
            PdfStatus.SEARCH_FAILED,
            "resolve-recorded-search-failure-before-absence-claim",
        )
    return (
        PdfStatus.NOT_YET_SEARCHED,
        "search-explicitly-authorized-roots",
    )


def _coverage_evidence(
    evidence: ReferenceCoverage | None,
) -> tuple[str, ...]:
    if evidence is None:
        return ()
    values = set(evidence.evidence)
    values.update(
        f"candidate-content:sha256:{candidate.sha256}"
        for candidate in evidence.candidates
    )
    return tuple(sorted(values))


def _access_status(
    *,
    matched_pdf: ManagedPdf | None,
    evidence: ReferenceCoverage | None,
) -> str:
    if matched_pdf is not None:
        return "managed-local-access"
    if evidence is None:
        return "not-assessed"
    if evidence.access_state is not CoverageAccessState.NONE:
        return evidence.access_state.value
    if evidence.candidates:
        return "candidate-access-unverified"
    return "searched-no-access-evidence"


def _pdf_expectation(record: ReferenceCandidate) -> PdfExpectation:
    source_type = _source_type(record)
    if record.entry_type.lower() in _EXPECTED_PDF_TYPES:
        return PdfExpectation.EXPECTED
    if source_type == "preprint":
        return PdfExpectation.EXPECTED
    if source_type in {
        "manual-or-documentation",
        "software-repository",
        "website",
    }:
        return PdfExpectation.NOT_APPLICABLE
    return PdfExpectation.REVIEW


def _source_type(record: ReferenceCandidate) -> str:
    entry_type = record.entry_type.lower()
    if entry_type == "misc":
        if record.eprint or (
            record.doi is not None and record.doi.startswith("10.48550/arxiv.")
        ):
            return "preprint"
        if record.url:
            hostname = (urlparse(record.url).hostname or "").lower()
            if hostname in {"github.com", "www.github.com"}:
                return "software-repository"
            return "website"
        return "miscellaneous"
    return {
        "article": "journal-article",
        "book": "book",
        "inproceedings": "conference-paper",
        "conference": "conference-paper",
        "manual": "manual-or-documentation",
    }.get(entry_type, entry_type)


def _full_text_expected(expectation: PdfExpectation) -> bool | None:
    if expectation is PdfExpectation.EXPECTED:
        return True
    if expectation is PdfExpectation.NOT_APPLICABLE:
        return False
    return None


def _coverage_claims(
    *,
    coverage_observation: CoverageObservation | None,
    processing_supplied: bool,
    citation_closure_supplied: bool,
) -> tuple[str, ...]:
    values = {
        "preserved-bibliography-bytes",
        "collection-row-evidence",
        "managed-pdf-directory",
        (
            "processing-evidence:supplied"
            if processing_supplied
            else "processing-evidence:not-supplied"
        ),
        (
            "citation-closure:supplied"
            if citation_closure_supplied
            else "citation-closure:not-supplied"
        ),
    }
    if processing_supplied:
        values.update(
            {
                "processing-contract:proposed",
                "processing-audit:recorded-producer-status",
                "processing-independent-revalidation:not-performed",
            }
        )
    if coverage_observation is None:
        values.update(
            {
                "pdf-coverage:not-supplied",
                "ambiguity:not-evaluated",
            }
        )
    else:
        values.update(
            {
                f"pdf-coverage:{coverage_observation.state.value}",
                f"pdf-coverage-id:{coverage_observation.coverage_id}",
                "source-revision:asserted-not-verified",
                f"ambiguity:{coverage_observation.ambiguity_evaluation.value}",
                "authorized-roots:"
                + ",".join(coverage_observation.authorized_root_aliases),
                f"coverage-exclusions:{len(coverage_observation.exclusions)}",
                f"coverage-failures:{len(coverage_observation.failures)}",
            }
        )
    return tuple(sorted(values))


def _counts(
    references: tuple[CollectionReference, ...],
    extras: tuple[ExtraPdf, ...],
    citation_closure: CitationClosure | None,
) -> dict[str, int]:
    counts = {
        "references": len(references),
        "managed_pdfs": sum(
            record.managed_pdf is not None for record in references
        ),
        "missing_expected_pdfs": sum(
            record.pdf_expectation is PdfExpectation.EXPECTED
            and record.managed_pdf is None
            for record in references
        ),
        "not_yet_searched": sum(
            record.pdf_status is PdfStatus.NOT_YET_SEARCHED
            for record in references
        ),
        "search_incomplete": sum(
            record.pdf_status is PdfStatus.SEARCH_INCOMPLETE
            for record in references
        ),
        "search_failed": sum(
            record.pdf_status is PdfStatus.SEARCH_FAILED
            for record in references
        ),
        "not_located": sum(
            record.pdf_status is PdfStatus.NOT_LOCATED for record in references
        ),
        "located_unverified": sum(
            record.pdf_status is PdfStatus.LOCATED_UNVERIFIED
            for record in references
        ),
        "ambiguous_matches": sum(
            record.pdf_status is PdfStatus.AMBIGUOUS_MATCHES
            for record in references
        ),
        "alternate_version_only": sum(
            record.pdf_status is PdfStatus.ALTERNATE_VERSION_ONLY
            for record in references
        ),
        "cloud_placeholders": sum(
            record.pdf_status is PdfStatus.CLOUD_PLACEHOLDER
            for record in references
        ),
        "access_controlled": sum(
            record.pdf_status is PdfStatus.ACCESS_CONTROLLED
            for record in references
        ),
        "full_text_not_public": sum(
            record.pdf_status is PdfStatus.FULL_TEXT_NOT_PUBLIC
            for record in references
        ),
        "pdf_applicability_review": sum(
            record.pdf_status is PdfStatus.PDF_APPLICABILITY_REVIEW
            for record in references
        ),
        "pdf_not_applicable": sum(
            record.pdf_status is PdfStatus.PDF_NOT_APPLICABLE
            for record in references
        ),
        "extra_pdfs": len(extras),
        "seed_raw_extractions": sum(
            record.ingestion_status
            == "completed-source-bound-reference-evidence"
            for record in references
        ),
        "seed_transcripts_with_recorded_passing_audit": sum(
            record.transcript_status
            == "automated-unreviewed-with-recorded-passing-audit"
            for record in references
        ),
        "extra_raw_extractions": sum(
            extra.ingestion_status
            == "completed-source-bound-reference-evidence"
            for extra in extras
        ),
        "extra_transcripts_with_recorded_passing_audit": sum(
            extra.transcript_status
            == "automated-unreviewed-with-recorded-passing-audit"
            for extra in extras
        ),
        "duplicate_content_groups": len(
            {
                tuple(
                    sorted(
                        (
                            record.proposed_citekey,
                            *record.duplicate_citekeys,
                        )
                    )
                )
                for record in references
                if record.duplicate_citekeys
            }
        ),
        "cited_and_defined": 0,
        "cited_but_undefined": 0,
        "defined_but_uncited": 0,
    }
    if citation_closure is not None:
        counts.update(
            {
                "cited_and_defined": len(citation_closure.cited_and_defined),
                "cited_but_undefined": len(
                    citation_closure.cited_but_undefined
                ),
                "defined_but_uncited": len(
                    citation_closure.defined_but_uncited
                ),
            }
        )
    return counts


def _render_outputs(
    manifest: CollectionManifest,
    closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None,
) -> dict[str, bytes]:
    missing_rows = [
        record
        for record in manifest.references
        if record.pdf_expectation is PdfExpectation.EXPECTED
        and record.managed_pdf is None
    ]
    ambiguous_rows = [
        record
        for record in manifest.references
        if record.pdf_status is PdfStatus.AMBIGUOUS_MATCHES
    ]
    return {
        "collection-manifest.json": manifest.to_json().encode("utf-8"),
        "citation-closure.json": (
            closure.to_json().encode("utf-8")
            if closure is not None
            else pretty_json(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "status": "not-supplied",
                    "asserted_source_revision": (
                        manifest.asserted_source_revision
                    ),
                }
            ).encode("utf-8")
        ),
        "coverage-observation.json": (
            coverage_observation.to_json().encode("utf-8")
            if coverage_observation is not None
            else pretty_json(
                {
                    "schema_version": 1,
                    "status": "not-supplied",
                    "ambiguity_evaluation": "not-evaluated",
                }
            ).encode("utf-8")
        ),
        "missing-pdfs.csv": _reference_csv(missing_rows).encode("utf-8"),
        "ambiguous-pdfs.csv": _reference_csv(ambiguous_rows).encode("utf-8"),
        "extra-pdfs.csv": _extra_csv(manifest.extra_pdfs).encode("utf-8"),
    }


def _reference_csv(records: list[CollectionReference]) -> str:
    stream = io.StringIO(newline="")
    fields = (
        "proposed_citekey",
        "identity_status",
        "citekey_status",
        "entry_type",
        "source_type",
        "full_text_expected",
        "title",
        "year",
        "doi",
        "source_bibliographies",
        "metadata_verification_status",
        "pdf_expectation",
        "pdf_status",
        "access_status",
        "rights_status",
        "ingestion_status",
        "transcript_status",
        "next_lawful_action",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "proposed_citekey": record.proposed_citekey,
                "identity_status": record.identity_status,
                "citekey_status": record.citekey_status,
                "entry_type": record.entry_type,
                "source_type": record.source_type,
                "full_text_expected": (
                    ""
                    if record.full_text_expected is None
                    else str(record.full_text_expected).lower()
                ),
                "title": record.title or "",
                "year": record.year or "",
                "doi": record.doi or "",
                "source_bibliographies": ";".join(record.source_bibliographies),
                "metadata_verification_status": (
                    record.metadata_verification_status
                ),
                "pdf_expectation": record.pdf_expectation,
                "pdf_status": record.pdf_status,
                "access_status": record.access_status,
                "rights_status": record.rights_status,
                "ingestion_status": record.ingestion_status,
                "transcript_status": record.transcript_status,
                "next_lawful_action": record.next_lawful_action,
            }
        )
    return stream.getvalue()


def _extra_csv(extras: tuple[ExtraPdf, ...]) -> str:
    stream = io.StringIO(newline="")
    fields = (
        "filename",
        "proposed_citekey",
        "sha256",
        "byte_size",
        "duplicate_citekeys",
        "access_status",
        "rights_status",
        "ingestion_status",
        "transcript_status",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for extra in extras:
        writer.writerow(
            {
                "filename": extra.filename,
                "proposed_citekey": extra.proposed_citekey,
                "sha256": extra.sha256,
                "byte_size": extra.byte_size,
                "duplicate_citekeys": ";".join(extra.duplicate_citekeys),
                "access_status": extra.access_status,
                "rights_status": extra.rights_status,
                "ingestion_status": extra.ingestion_status,
                "transcript_status": extra.transcript_status,
            }
        )
    return stream.getvalue()


def _stable_id(kind: str, payload: object) -> str:
    canonical = canonical_json_bytes(payload)
    return f"{kind}:sha256:{hashlib.sha256(canonical).hexdigest()}"
