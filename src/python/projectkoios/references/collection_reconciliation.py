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

from projectkoios.references.acquisition import AcquisitionProjection
from projectkoios.references.assets import AssetDiscoveryPlan
from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.io_limits import (
    RECONCILIATION_IO_LIMITS,
    RECONCILIATION_PACKAGE_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_csv_field_size,
    bounded_utf8_size,
    validate_json_text_nesting,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    CloudRootMutationError,
    PathLimitError,
    PathSafetyError,
    PlaceholderObservation,
    PlaceholderPreflightError,
    PlaceholderStatus,
    RootPreflightEvidence,
    RootStorageClass,
    authorize_root_preflight,
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
from projectkoios.references.review import ReviewProjection
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
    StateKnowledge,
    StateResolution,
    build_reference_state_projection,
)

_SCHEMA_VERSION = 4
_PROCESSOR_VERSION = "0.9.0"
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
class CitationUse:
    citekey: str
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class CitationClosure:
    schema_version: int
    asserted_source_revision: str
    root_preflight: RootPreflightEvidence
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


def load_collection_rows(
    path: Path,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> EvidenceMapping[CollectionRowEvidence]:
    root_preflight = authorize_root_preflight(
        root_alias="collection-rows",
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    max_csv_bytes = _required_limit(limits.max_csv_bytes, "max_csv_bytes")
    try:
        content = read_path_bytes(
            path,
            label="collection rows",
            root_alias="collection-rows",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
            max_bytes=max_csv_bytes,
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CollectionReconciliationError(
            "collection rows are not UTF-8"
        ) from error
    max_rows = _required_limit(limits.max_rows, "max_rows")
    max_text_bytes = _required_limit(
        limits.max_text_bytes,
        "max_text_bytes",
    )
    result: dict[str, CollectionRowEvidence] = {}
    source_content_id = "blob:sha256:" + hashlib.sha256(content).hexdigest()
    try:
        with bounded_csv_field_size(max_text_bytes):
            rows = csv.DictReader(io.StringIO(text, newline=""))
            for row_number, row in enumerate(rows, start=1):
                if row_number > max_rows:
                    raise ReferenceIOLimitError(
                        resource="collection rows",
                        limit_name="max_rows",
                        limit=max_rows,
                        observed=row_number,
                        limits=limits,
                    )
                for field_name, field_value in row.items():
                    if field_value is None:
                        continue
                    field_bytes = bounded_utf8_size(
                        field_value,
                        max_bytes=max_text_bytes,
                    )
                    if field_bytes > max_text_bytes:
                        raise ReferenceIOLimitError(
                            resource=(
                                f"collection row {row_number} field "
                                f"{field_name}"
                            ),
                            limit_name="max_text_bytes",
                            limit=max_text_bytes,
                            observed=field_bytes,
                            limits=limits,
                        )
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
                    for item in (row.get("source_bibliographies") or "").split(
                        ";"
                    )
                    if item
                )
                max_sources = _required_limit(
                    limits.max_candidates,
                    "max_candidates",
                )
                if len(sources) > max_sources:
                    raise ReferenceIOLimitError(
                        resource=(f"collection row {row_number} source list"),
                        limit_name="max_candidates",
                        limit=max_sources,
                        observed=len(sources),
                        limits=limits,
                    )
                bibliographic_status = (
                    row.get("bibliographic_status") or "unrecorded"
                )
                reading_status = row.get("reading_status") or "unrecorded"
                row_payload = {
                    "source_content_id": source_content_id,
                    "row_index": row_number - 1,
                    "parser_name": "projectkoios-collection-csv",
                    "parser_version": _COLLECTION_ROWS_PARSER_VERSION,
                    "source_bibliographies": sources,
                    "bibliographic_status": bibliographic_status,
                    "reading_status": reading_status,
                }
                result[citekey] = CollectionRowEvidence(
                    source_bibliographies=sources,
                    bibliographic_status=bibliographic_status,
                    reading_status=reading_status,
                    observation_id=_stable_id(
                        "collection-row-observation", row_payload
                    ),
                    source_content_id=source_content_id,
                    row_index=row_number - 1,
                    parser_name="projectkoios-collection-csv",
                    parser_version=_COLLECTION_ROWS_PARSER_VERSION,
                )
    except csv.Error as error:
        if "field larger than field limit" in str(error):
            raise ReferenceIOLimitError(
                resource="collection rows CSV field",
                limit_name="max_text_bytes",
                limit=max_text_bytes,
                observed=max_text_bytes + 1,
                limits=limits,
            ) from error
        raise CollectionReconciliationError(
            "collection rows CSV is malformed"
        ) from error
    return EvidenceMapping(
        entries=tuple(sorted(result.items())),
        input_evidence=(
            ContentEvidence.from_bytes(
                role="collection-rows",
                filename="inputs/collection-rows.csv",
                content=content,
            ),
        ),
        root_preflights=(root_preflight,),
    )


def scan_managed_pdfs(
    directory: Path,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    source_discovery: Path | None = None,
    source_discovery_storage_class: RootStorageClass | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> ManagedPdfScan:
    try:
        root = AuthorizedRoot.existing(
            directory,
            label="managed PDF root",
            root_alias="managed-pdfs",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        relative_files = root.iter_files(
            suffix=".pdf",
            recursive=False,
            max_files=_required_limit(limits.max_files, "max_files"),
            max_entries=_required_limit(limits.max_entries, "max_entries"),
            max_depth=1,
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    except PlaceholderPreflightError:
        raise
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    if (source_discovery is None) != (source_discovery_storage_class is None):
        raise ValueError(
            "source discovery path and storage class must be supplied together"
        )
    historical: dict[str, tuple[str, tuple[str, ...]]]
    discovery_evidence: tuple[ContentEvidence, ...]
    if source_discovery is None:
        historical, discovery_evidence = {}, ()
    else:
        assert source_discovery_storage_class is not None
        historical, discovery_evidence = _load_source_discovery(
            source_discovery,
            storage_class=source_discovery_storage_class,
            placeholder_probe=placeholder_probe,
            limits=limits,
        )
    pdfs: list[ManagedPdf] = []
    file_observations: list[PlaceholderObservation] = []
    asset_evidence: list[ContentEvidence] = []
    total_bytes = 0
    max_file_bytes = _required_limit(limits.max_file_bytes, "max_file_bytes")
    max_total_bytes = _required_limit(
        limits.max_total_bytes,
        "max_total_bytes",
    )
    for relative in relative_files:
        try:
            citekey = validate_citekey(Path(relative.name).stem)
            preflight = root.preflight_file(relative)
            if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
                raise PlaceholderPreflightError(preflight)
            observation = root.observe_file(
                relative,
                max_bytes=max_file_bytes,
                prefix_bytes=5,
            )
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        except PlaceholderPreflightError:
            raise
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        byte_size = observation.byte_size
        if byte_size <= 0:
            raise CollectionReconciliationError(
                f"managed PDF size is outside bounds: {relative.name}"
            )
        if observation.prefix != b"%PDF-":
            raise CollectionReconciliationError(
                f"managed file lacks PDF header: {relative.name}"
            )
        total_bytes += byte_size
        if total_bytes > max_total_bytes:
            raise ReferenceIOLimitError(
                resource="managed PDFs",
                limit_name="max_total_bytes",
                limit=max_total_bytes,
                observed=total_bytes,
                limits=limits,
            )
        digest = observation.sha256
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
        root_preflight=root.preflight_evidence,
        file_observations=tuple(
            sorted(
                file_observations,
                key=lambda item: item.relative_path or "",
            )
        ),
    )


def build_citation_closure(
    manuscript_root: Path,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    bibliography_keys: tuple[str, ...],
    source_revision: str,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> CitationClosure:
    try:
        root = AuthorizedRoot.existing(
            manuscript_root,
            label="manuscript root",
            root_alias="manuscript-sources",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        source_files = root.iter_files(
            suffix=".tex",
            recursive=True,
            max_files=_required_limit(limits.max_files, "max_files"),
            max_entries=_required_limit(limits.max_entries, "max_entries"),
            max_depth=64,
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error

    uses: dict[str, set[str]] = defaultdict(set)
    nocite_all = False
    relative_files: list[str] = []
    source_file_evidence: list[ContentEvidence] = []
    total_bytes = 0
    for relative_path in source_files:
        try:
            content = root.read_bytes(
                relative_path,
                max_bytes=_required_limit(
                    limits.max_text_file_bytes,
                    "max_text_file_bytes",
                ),
            )
            text = content.decode("utf-8")
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        except (PathSafetyError, UnicodeDecodeError) as error:
            raise CollectionReconciliationError(
                f"cannot safely read TeX source: {relative_path}"
            ) from error
        total_bytes += len(content)
        max_text_bytes = _required_limit(
            limits.max_text_total_bytes,
            "max_text_total_bytes",
        )
        if total_bytes > max_text_bytes:
            raise ReferenceIOLimitError(
                resource="TeX sources",
                limit_name="max_text_total_bytes",
                limit=max_text_bytes,
                observed=total_bytes,
                limits=limits,
            )
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
    verified_source_tree = (
        _verify_source_tree(
            root.path,
            asserted_revision=source_revision,
        )
        if storage_class is RootStorageClass.LOCAL
        else None
    )
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "asserted_source_revision": source_revision,
        "root_preflight": root.preflight_evidence,
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
        root_preflight=root.preflight_evidence,
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
    acquisition_evidence: Mapping[str, AcquisitionProjection] | None = None,
    review_projection: ReviewProjection | None = None,
    catalog_assets: Mapping[str, tuple[SourceAssetRecord, ...]] | None = None,
    asset_plan: AssetDiscoveryPlan | None = None,
    bibliography_parser: str = "caller-supplied-records",
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> ReconciliationOutputs:
    if getattr(managed_pdfs, "file_observations", ()):
        raise CollectionReconciliationError(
            "complete reconciliation cannot consume skipped managed-PDF "
            "observations"
        )
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
    max_records = _required_limit(limits.max_candidates, "max_candidates")
    if not records:
        raise CollectionReconciliationError("bibliography has no records")
    if len(records) > max_records:
        raise ReferenceIOLimitError(
            resource="bibliography records",
            limit_name="max_candidates",
            limit=max_records,
            observed=len(records),
            limits=limits,
        )
    max_files = _required_limit(limits.max_files, "max_files")
    if len(managed_pdfs) > max_files:
        raise ReferenceIOLimitError(
            resource="managed PDF observations",
            limit_name="max_files",
            limit=max_files,
            observed=len(managed_pdfs),
            limits=limits,
        )
    max_rows = _required_limit(limits.max_rows, "max_rows")
    if len(collection_rows) > max_rows:
        raise ReferenceIOLimitError(
            resource="collection row observations",
            limit_name="max_rows",
            limit=max_rows,
            observed=len(collection_rows),
            limits=limits,
        )
    if (
        processing_evidence is not None
        and len(processing_evidence) > max_records
    ):
        raise ReferenceIOLimitError(
            resource="processing evidence observations",
            limit_name="max_candidates",
            limit=max_records,
            observed=len(processing_evidence),
            limits=limits,
        )
    if (
        acquisition_evidence is not None
        and len(acquisition_evidence) > max_records
    ):
        raise ReferenceIOLimitError(
            resource="acquisition evidence observations",
            limit_name="max_candidates",
            limit=max_records,
            observed=len(acquisition_evidence),
            limits=limits,
        )
    if asset_plan is not None and not isinstance(
        asset_plan, AssetDiscoveryPlan
    ):
        raise CollectionReconciliationError(
            "asset_plan must be a typed AssetDiscoveryPlan"
        )
    catalog_asset_count = sum(
        len(values) for values in (catalog_assets or {}).values()
    )
    if catalog_asset_count > max_records:
        raise ReferenceIOLimitError(
            resource="catalog asset observations",
            limit_name="max_candidates",
            limit=max_records,
            observed=catalog_asset_count,
            limits=limits,
        )
    if asset_plan is not None and len(asset_plan.candidates) > max_records:
        raise ReferenceIOLimitError(
            resource="asset plan candidates",
            limit_name="max_candidates",
            limit=max_records,
            observed=len(asset_plan.candidates),
            limits=limits,
        )
    max_bibliography_bytes = _required_limit(
        limits.max_bibliography_bytes,
        "max_bibliography_bytes",
    )
    if len(bibliography_bytes) > max_bibliography_bytes:
        raise ReferenceIOLimitError(
            resource="bibliography bytes",
            limit_name="max_bibliography_bytes",
            limit=max_bibliography_bytes,
            observed=len(bibliography_bytes),
            limits=limits,
        )
    processing_supplied = processing_evidence is not None
    processing_by_citekey = processing_evidence or {}
    acquisition_supplied = acquisition_evidence is not None
    acquisition_by_citekey = acquisition_evidence or {}
    catalog_assets_by_citekey = catalog_assets or {}
    if review_projection is not None and not isinstance(
        review_projection, ReviewProjection
    ):
        raise CollectionReconciliationError(
            "review_projection must be a replayed ReviewProjection"
        )
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
        for citekey in acquisition_by_citekey:
            validate_citekey(
                citekey,
                field="acquisition-evidence citekey",
            )
        for citekey in catalog_assets_by_citekey:
            validate_citekey(citekey, field="catalog-asset citekey")
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
    preflight_by_citekey: dict[str, PlaceholderObservation] = {}
    for item in getattr(managed_pdfs, "file_observations", ()):
        if item.relative_path is None:
            raise CollectionReconciliationError(
                "managed-root file observation has no relative path"
            )
        citekey = validate_citekey(Path(item.relative_path).stem)
        if citekey in preflight_by_citekey or citekey in by_citekey:
            raise CollectionReconciliationError(
                "managed PDF preflight has duplicate citekey stems"
            )
        preflight_by_citekey[citekey] = item
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
    unmatched_acquisition = sorted(set(acquisition_by_citekey) - set(citekeys))
    if unmatched_acquisition:
        raise CollectionReconciliationError(
            "acquisition evidence has no matching candidate: "
            f"{unmatched_acquisition}"
        )
    if any(
        not isinstance(item, AcquisitionProjection)
        for item in acquisition_by_citekey.values()
    ):
        raise CollectionReconciliationError(
            "supplied acquisition evidence is not a typed projection"
        )
    unmatched_catalog_assets = sorted(
        set(catalog_assets_by_citekey) - set(citekeys)
    )
    if unmatched_catalog_assets:
        raise CollectionReconciliationError(
            "catalog assets have no matching candidate: "
            f"{unmatched_catalog_assets}"
        )
    if any(
        not isinstance(values, tuple)
        or any(not isinstance(item, SourceAssetRecord) for item in values)
        for values in catalog_assets_by_citekey.values()
    ):
        raise CollectionReconciliationError(
            "catalog assets must be typed immutable tuples"
        )
    candidate_ids = {item.candidate_id for item in ordered_records}
    if asset_plan is not None:
        unmatched_plan = sorted(
            {
                item.candidate_id
                for item in asset_plan.candidates
                if item.candidate_id not in candidate_ids
            }
        )
        if unmatched_plan:
            raise CollectionReconciliationError(
                f"asset plan has no matching candidates: {unmatched_plan}"
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
    state_projections: list[ReferenceStateProjection] = []
    for record in ordered_records:
        evidence = collection_rows[record.proposed_citekey]
        matched_pdf = by_citekey.get(record.proposed_citekey)
        expectation = _pdf_expectation(record)
        processing = processing_by_citekey.get(
            record.proposed_citekey,
            ProcessingEvidence.not_supplied(),
        )
        acquisition = acquisition_by_citekey.get(record.proposed_citekey)
        coverage_item = coverage_by_citekey.get(record.proposed_citekey)
        preflight_item = preflight_by_citekey.get(record.proposed_citekey)
        status, next_action = _classify_pdf_status(
            matched_pdf=matched_pdf,
            expectation=expectation,
            observation=coverage_observation,
            evidence=coverage_item,
            preflight=preflight_item,
        )
        plan_candidates = (
            asset_plan.connected_candidates((record.candidate_id,))
            if asset_plan is not None
            else ()
        )
        if matched_pdf is None and asset_plan is not None and plan_candidates:
            status, next_action = _classify_asset_plan_status(
                candidate_id=record.candidate_id,
                asset_plan=asset_plan,
                fallback=(status, next_action),
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
        citation_status = (
            CitationStatus.CLOSURE_UNAVAILABLE
            if citation_closure is None
            else (
                CitationStatus.CITED_DEFINED
                if record.proposed_citekey in cited
                else CitationStatus.DEFINED_UNCITED
            )
        )
        state_projection = build_reference_state_projection(
            candidate=record,
            collection_id=collection_id,
            collection_row=evidence,
            managed_asset=matched_pdf,
            acquisition=acquisition,
            processing=(
                processing
                if processing.evidence_record_id is not None
                else None
            ),
            review=review_projection,
            coverage=coverage_observation,
            catalog_assets=catalog_assets_by_citekey.get(
                record.proposed_citekey, ()
            ),
            asset_plan=asset_plan,
            citation_status=(
                citation_status.value if citation_closure is not None else None
            ),
            citation_input_id=(
                citation_closure.closure_id
                if citation_closure is not None
                else None
            ),
        )
        state_projections.append(state_projection)
        discrepancy_fields = tuple(
            item.field
            for item in state_projection.fields
            if item.resolution is StateResolution.DISCREPANCY
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
                reading_decision_status=_projected_status(
                    state_projection,
                    "reading_decision",
                ),
                citation_status=citation_status,
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
                    else (
                        tuple(
                            sorted(
                                item.observation_id for item in plan_candidates
                            )
                        )
                        if plan_candidates
                        else (
                            _preflight_evidence(preflight_item)
                            if preflight_item is not None
                            else _coverage_evidence(coverage_item)
                        )
                    )
                ),
                duplicate_citekeys=duplicate_citekeys,
                acquisition_status=_projected_status(
                    state_projection,
                    "acquisition_status",
                ),
                access_status=_projected_status(
                    state_projection,
                    "access_status",
                ),
                rights_status=_projected_status(
                    state_projection,
                    "rights_status",
                ),
                ingestion_status=processing.ingestion_status,
                transcript_status=processing.transcript_status,
                state_projection_id=state_projection.projection_id,
                state_discrepancy_fields=discrepancy_fields,
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
        acquisition_supplied=acquisition_supplied,
        review_supplied=review_projection is not None,
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
        "state_projections": [
            json.loads(item.to_json()) for item in state_projections
        ],
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
        state_projections=tuple(state_projections),
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
        acquisition_evidence=acquisition_evidence,
        review_projection=review_projection,
        catalog_assets=catalog_assets,
        asset_plan=asset_plan,
        limits=limits,
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
            SoftwareIdentity(
                name="reference-io-limits",
                version="1",
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
    output_storage_class: RootStorageClass,
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
            root_alias="reconciliation-output-parent",
            storage_class=output_storage_class,
        )
        output_name = validate_relative_path(
            output_directory.name,
            field="output directory name",
        )
        output_state = parent.state(output_name)
    except CloudRootMutationError, PlaceholderPreflightError:
        raise
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
                root_alias="reconciliation-output",
                storage_class=RootStorageClass.LOCAL,
            )
            directory_limit = min(
                _required_limit(
                    RECONCILIATION_PACKAGE_IO_LIMITS.max_entries,
                    "max_entries",
                ),
                len(expected) + 1,
            )
            actual_names = {
                path.name
                for path in existing.iter_files(
                    suffix="",
                    recursive=False,
                    reject_directories=True,
                    max_files=directory_limit,
                    max_entries=directory_limit,
                    max_depth=1,
                )
            }
            if actual_names != set(expected):
                raise CollectionReconciliationError(
                    "existing reconciliation output is incomplete or unexpected"
                )
            max_package_file_bytes = _required_limit(
                RECONCILIATION_PACKAGE_IO_LIMITS.max_file_bytes,
                "max_file_bytes",
            )
            for name, content in expected.items():
                observation = existing.observe_file(
                    name,
                    max_bytes=max_package_file_bytes,
                )
                if (
                    observation.byte_size != len(content)
                    or observation.sha256 != hashlib.sha256(content).hexdigest()
                ):
                    raise CollectionReconciliationError(
                        "existing reconciliation output differs"
                    )
        except PathLimitError as error:
            raise _limit_error(
                error,
                RECONCILIATION_PACKAGE_IO_LIMITS,
            ) from error
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
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    expected_package_id: str | None = None,
) -> LoadedReconciliationPackage:
    try:
        loaded = load_reconciliation_package(
            directory,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
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
    output_storage_class: RootStorageClass,
) -> PublicationResult:
    """Replay deterministic bytes through immutable publication semantics."""
    return publish_reconciliation(
        outputs,
        output_directory=output_directory,
        output_storage_class=output_storage_class,
    )


def _bound_input_evidence(
    *,
    bibliography_bytes: bytes,
    collection_rows: Mapping[str, CollectionRowEvidence],
    managed_pdfs: Sequence[ManagedPdf],
    citation_closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None,
    coverage_observation_bytes: bytes | None,
    processing_evidence: Mapping[str, ProcessingEvidence] | None,
    acquisition_evidence: Mapping[str, AcquisitionProjection] | None,
    review_projection: ReviewProjection | None,
    catalog_assets: Mapping[str, tuple[SourceAssetRecord, ...]] | None,
    asset_plan: AssetDiscoveryPlan | None,
    limits: ReferenceIOLimits,
) -> tuple[ContentEvidence, ...]:
    evidence = [
        ContentEvidence.from_bytes(
            role="bibliography",
            filename="inputs/bibliography.bib",
            content=bibliography_bytes,
        ),
        ContentEvidence.from_bytes(
            role="effective-io-limits",
            filename="inputs/effective-io-limits.json",
            content=canonical_json_bytes(
                {
                    "schema_version": 1,
                    "coverage_status": "complete",
                    "effective_limits": limits.to_dict(),
                    "effective_limits_id": limits.evidence_id,
                }
            ),
        ),
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
    if acquisition_evidence is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="acquisition-projection",
                filename="inputs/acquisition-projections.json",
                content=canonical_json_bytes(
                    {
                        key: asdict(value)
                        for key, value in sorted(acquisition_evidence.items())
                    }
                ),
            )
        )
    if review_projection is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="review-projection",
                filename="inputs/review-projection.json",
                content=review_projection.to_json().encode("utf-8"),
            )
        )
    if catalog_assets is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="catalog-asset-observations",
                filename="inputs/catalog-assets.json",
                content=canonical_json_bytes(dict(catalog_assets)),
            )
        )
    if asset_plan is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="asset-discovery-plan",
                filename="inputs/asset-discovery-plan.json",
                content=asset_plan.to_json().encode("utf-8"),
            )
        )
    normalized = canonical_json_bytes(
        {
            "collection_rows": dict(collection_rows),
            "collection_rows_root_preflights": getattr(
                collection_rows, "root_preflights", ()
            ),
            "managed_pdfs": tuple(managed_pdfs),
            "managed_root_preflight": getattr(
                managed_pdfs, "root_preflight", None
            ),
            "managed_file_observations": getattr(
                managed_pdfs, "file_observations", ()
            ),
            "coverage_observation": coverage_observation,
            "processing_evidence": (
                None
                if processing_evidence is None
                else dict(processing_evidence)
            ),
            "processing_evidence_root_preflights": getattr(
                processing_evidence, "root_preflights", ()
            ),
            "acquisition_evidence": (
                None
                if acquisition_evidence is None
                else {
                    key: asdict(value)
                    for key, value in sorted(acquisition_evidence.items())
                }
            ),
            "review_projection_id": (
                None
                if review_projection is None
                else review_projection.projection_id
            ),
            "catalog_assets": (
                None if catalog_assets is None else dict(catalog_assets)
            ),
            "asset_plan": asset_plan,
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
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> tuple[
    dict[str, tuple[str, tuple[str, ...]]],
    tuple[ContentEvidence, ...],
]:
    if path is None:
        return {}, ()
    try:
        content = read_path_bytes(
            path,
            label="source-discovery document",
            root_alias="source-discovery",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
            max_bytes=_required_limit(
                limits.max_json_bytes,
                "max_json_bytes",
            ),
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    try:
        text = content.decode("utf-8")
        validate_json_text_nesting(
            text,
            limits=limits,
            resource="source discovery JSON",
        )
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionReconciliationError(
            "source-discovery document is invalid"
        ) from error
    _validate_json_depth(data, limits=limits, resource="source discovery")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CollectionReconciliationError(
            "unsupported source-discovery document"
        )
    matches = data.get("matches")
    if not isinstance(matches, list):
        raise CollectionReconciliationError(
            "source-discovery matches are invalid"
        )
    max_records = _required_limit(limits.max_candidates, "max_candidates")
    if len(matches) > max_records:
        raise ReferenceIOLimitError(
            resource="source-discovery matches",
            limit_name="max_candidates",
            limit=max_records,
            observed=len(matches),
            limits=limits,
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
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(basis, str)
            or not basis
        ):
            raise CollectionReconciliationError(
                "source-discovery match identity is incomplete"
            )
        maximum_text = _required_limit(
            limits.max_text_bytes,
            "max_text_bytes",
        )
        basis_bytes = bounded_utf8_size(
            basis,
            max_bytes=maximum_text,
        )
        if basis_bytes > maximum_text:
            raise ReferenceIOLimitError(
                resource="source-discovery match basis",
                limit_name="max_text_bytes",
                limit=maximum_text,
                observed=basis_bytes,
                limits=limits,
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


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(
            f"collection-reconciliation I/O profile must define {name}"
        )
    return value


def _limit_error(
    error: PathLimitError,
    limits: ReferenceIOLimits,
) -> ReferenceIOLimitError:
    return ReferenceIOLimitError(
        resource=error.resource,
        limit_name=error.limit_name,
        limit=error.limit,
        observed=error.observed,
        limits=limits,
    )


def _validate_json_depth(
    value: object,
    *,
    limits: ReferenceIOLimits,
    resource: str,
) -> None:
    max_depth = _required_limit(limits.max_json_depth, "max_json_depth")
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            raise ReferenceIOLimitError(
                resource=resource,
                limit_name="max_json_depth",
                limit=max_depth,
                observed=depth,
                limits=limits,
            )
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


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
    preflight: PlaceholderObservation | None = None,
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
    if preflight is not None:
        if preflight.status is PlaceholderStatus.CLOUD_PLACEHOLDER:
            return (
                PdfStatus.CLOUD_PLACEHOLDER,
                "request-explicit-placeholder-hydration-authorization",
            )
        if preflight.status in {
            PlaceholderStatus.ACCESS_CONTROLLED,
            PlaceholderStatus.UNREADABLE,
        }:
            return (
                PdfStatus.ACCESS_CONTROLLED,
                "resolve-local-file-access-without-bypassing-controls",
            )
        raise CollectionReconciliationError(
            "managed-root preflight has unsupported result"
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


def _classify_asset_plan_status(
    *,
    candidate_id: str,
    asset_plan: AssetDiscoveryPlan,
    fallback: tuple[PdfStatus, str],
) -> tuple[PdfStatus, str]:
    ambiguity = asset_plan.ambiguity_status(candidate_id)
    if fallback[0] not in {
        PdfStatus.NOT_YET_SEARCHED,
        PdfStatus.NOT_LOCATED,
        PdfStatus.SEARCH_INCOMPLETE,
        PdfStatus.SEARCH_FAILED,
    }:
        if ambiguity != "unresolved-single-heuristic-candidate":
            return (
                PdfStatus.AMBIGUOUS_MATCHES,
                "review-all-heuristic-candidates-versions-and-record-rejections",
            )
        return fallback
    if ambiguity == "unresolved-single-heuristic-candidate":
        return (
            PdfStatus.LOCATED_UNVERIFIED,
            "obtain-actor-provenanced-asset-identity-authorization",
        )
    return (
        PdfStatus.AMBIGUOUS_MATCHES,
        "review-all-heuristic-candidates-versions-and-record-rejections",
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


def _preflight_evidence(
    observation: PlaceholderObservation | None,
) -> tuple[str, ...]:
    if observation is None:
        return ()
    return (
        f"root-storage-class:{observation.storage_class.value}",
        f"placeholder-probe:{observation.probe_id}",
        f"path-preflight:{observation.status.value}",
    )


def _projected_status(
    projection: ReferenceStateProjection,
    field: str,
) -> str:
    projected = projection.field(field)
    if projected.resolution is StateResolution.DISCREPANCY:
        return StateResolution.DISCREPANCY.value
    if not projected.values:
        return StateKnowledge.NOT_OBSERVED.value
    value = projected.values[0]
    if value.knowledge is not StateKnowledge.OBSERVED:
        return value.knowledge.value
    parsed = value.value()
    if not isinstance(parsed, str):
        raise CollectionReconciliationError(
            f"projected {field} status is not text"
        )
    return parsed


def _access_status(
    *,
    matched_pdf: ManagedPdf | None,
    evidence: ReferenceCoverage | None,
    preflight: PlaceholderObservation | None = None,
) -> str:
    if matched_pdf is not None:
        return "managed-local-access"
    if preflight is not None:
        return preflight.status.value
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
    acquisition_supplied: bool,
    review_supplied: bool,
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
            "acquisition-evidence:supplied"
            if acquisition_supplied
            else "acquisition-evidence:not-supplied"
        ),
        (
            "review-evidence:supplied"
            if review_supplied
            else "review-evidence:not-supplied"
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
        "reference-state-projections.json": pretty_json(
            {
                "schema_version": 1,
                "artifact_kind": (
                    "projectkoios.references.collection-state-projections"
                ),
                "authoritative_input_ids": sorted(
                    {
                        input_id
                        for projection in manifest.state_projections
                        for input_id in projection.authoritative_input_ids
                    }
                ),
                "projections": [
                    json.loads(item.to_json())
                    for item in manifest.state_projections
                ],
                "exact_replay": True,
            }
        ).encode("utf-8"),
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
        "reading_decision_status",
        "pdf_expectation",
        "pdf_status",
        "acquisition_status",
        "access_status",
        "rights_status",
        "ingestion_status",
        "transcript_status",
        "state_projection_id",
        "state_discrepancy_fields",
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
                "reading_decision_status": record.reading_decision_status,
                "pdf_expectation": record.pdf_expectation,
                "pdf_status": record.pdf_status,
                "acquisition_status": record.acquisition_status,
                "access_status": record.access_status,
                "rights_status": record.rights_status,
                "ingestion_status": record.ingestion_status,
                "transcript_status": record.transcript_status,
                "state_projection_id": record.state_projection_id,
                "state_discrepancy_fields": ";".join(
                    record.state_discrepancy_fields
                ),
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
