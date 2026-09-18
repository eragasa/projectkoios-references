from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
import shutil
from collections import defaultdict
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.models import ReferenceRecord
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    PathSafetyError,
    read_path_text,
    validate_citekey,
    validate_relative_path,
)

_SCHEMA_VERSION = 1
_PROCESSOR_VERSION = "0.5.0"
_MAX_RECORDS = 10_000
_MAX_STATUS_JSON_BYTES = 10_000_000
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


@dataclass(frozen=True)
class ProcessingEvidence:
    ingestion_status: str
    transcript_status: str


@dataclass(frozen=True)
class ManagedPdf:
    filename: str
    citekey: str
    sha256: str
    byte_size: int
    historically_verified: bool
    discovery_evidence: tuple[str, ...]


@dataclass(frozen=True)
class CitationUse:
    citekey: str
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class CitationClosure:
    schema_version: int
    source_revision: str
    bibliography_keys: tuple[str, ...]
    explicit_uses: tuple[CitationUse, ...]
    cited_and_defined: tuple[str, ...]
    cited_but_undefined: tuple[str, ...]
    defined_but_uncited: tuple[str, ...]
    nocite_all: bool
    source_files: tuple[str, ...]
    closure_id: str

    def to_json(self) -> str:
        return _pretty_json(asdict(self))


@dataclass(frozen=True)
class CollectionReference:
    citekey: str
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
    source_revision: str
    bibliography_sha256: str
    coverage_observation_id: str | None
    coverage_state: CoverageState | None
    ambiguity_evaluation: AmbiguityEvaluation
    coverage: tuple[str, ...]
    references: tuple[CollectionReference, ...]
    extra_pdfs: tuple[ExtraPdf, ...]
    counts: dict[str, int]
    manifest_id: str

    def to_json(self) -> str:
        return _pretty_json(asdict(self))


@dataclass(frozen=True)
class ReconciliationOutputs:
    manifest: CollectionManifest
    citation_closure: CitationClosure | None
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class PublicationResult:
    status: str
    output_directory: Path
    manifest_id: str


def load_collection_rows(path: Path) -> dict[str, CollectionRowEvidence]:
    text = read_path_text(path, label="collection rows")
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
    return result


def scan_managed_pdfs(
    directory: Path,
    *,
    source_discovery: Path | None = None,
) -> tuple[ManagedPdf, ...]:
    try:
        root = AuthorizedRoot.existing(directory, label="managed PDF root")
        relative_files = root.iter_files(suffix=".pdf", recursive=False)
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    historical = _load_source_discovery(source_discovery)
    pdfs: list[ManagedPdf] = []
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
    return tuple(pdfs)


def scan_processing_evidence(
    ingestion_root: Path,
    *,
    citekeys: tuple[str, ...],
) -> dict[str, ProcessingEvidence]:
    try:
        root = AuthorizedRoot.existing(
            ingestion_root,
            label="ingestion root",
        )
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    result: dict[str, ProcessingEvidence] = {}
    for raw_citekey in sorted(set(citekeys)):
        try:
            citekey = validate_citekey(raw_citekey)
            extraction = f"{citekey}/extraction.json"
            extraction_state = root.state(extraction)
        except PathSafetyError as error:
            raise CollectionReconciliationError(
                f"unsafe processing lookup for citekey: {raw_citekey}"
            ) from error
        if extraction_state == "directory":
            raise CollectionReconciliationError(
                f"processing extraction is not a file: {citekey}"
            )
        ingestion_status = (
            "raw-extraction-present"
            if extraction_state == "regular"
            else "not-ingested"
        )
        transcript_status = _transcript_status(root, citekey)
        result[citekey] = ProcessingEvidence(
            ingestion_status=ingestion_status,
            transcript_status=transcript_status,
        )
    return result


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
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "source_revision": source_revision,
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
    }
    closure_id = _stable_id("citation-closure", payload)
    return CitationClosure(
        schema_version=_SCHEMA_VERSION,
        source_revision=source_revision,
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
        closure_id=closure_id,
    )


def reconcile_collection(
    records: tuple[ReferenceRecord, ...],
    *,
    bibliography_bytes: bytes,
    collection_id: str,
    source_revision: str,
    collection_rows: dict[str, CollectionRowEvidence],
    managed_pdfs: tuple[ManagedPdf, ...],
    citation_closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None = None,
    processing_evidence: dict[str, ProcessingEvidence] | None = None,
) -> ReconciliationOutputs:
    if not collection_id or not source_revision:
        raise CollectionReconciliationError(
            "collection and source revision must be non-empty"
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
    ordered_records = tuple(sorted(records, key=lambda item: item.citekey))
    try:
        citekeys = tuple(
            validate_citekey(record.citekey) for record in ordered_records
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
        citation_closure.source_revision != source_revision
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
        evidence = collection_rows[record.citekey]
        matched_pdf = by_citekey.get(record.citekey)
        expectation = _pdf_expectation(record)
        processing = processing_by_citekey.get(
            record.citekey,
            ProcessingEvidence(
                ingestion_status="not-assessed",
                transcript_status="not-assessed",
            ),
        )
        coverage_item = coverage_by_citekey.get(record.citekey)
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
                    if key != record.citekey
                )
            )
            if matched_pdf is not None
            else ()
        )
        references.append(
            CollectionReference(
                citekey=record.citekey,
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
                        if record.citekey in cited
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
                ProcessingEvidence("not-assessed", "not-assessed"),
            ).ingestion_status,
            transcript_status=processing_by_citekey.get(
                pdf.citekey,
                ProcessingEvidence("not-assessed", "not-assessed"),
            ).transcript_status,
        )
        for pdf in managed_pdfs
        if pdf.citekey not in seed
    )
    counts = _counts(tuple(references), extras, citation_closure)
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
        "source_revision": source_revision,
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
        source_revision=source_revision,
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
    return ReconciliationOutputs(
        manifest=manifest,
        citation_closure=citation_closure,
        files=tuple(sorted(rendered.items())),
    )


def publish_reconciliation(
    outputs: ReconciliationOutputs,
    *,
    output_directory: Path,
) -> PublicationResult:
    expected = dict(outputs.files)
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
            manifest_id=outputs.manifest.manifest_id,
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
        manifest_id=outputs.manifest.manifest_id,
    )


def _load_source_discovery(
    path: Path | None,
) -> dict[str, tuple[str, tuple[str, ...]]]:
    if path is None:
        return {}
    data = json.loads(
        read_path_text(
            path,
            label="source-discovery document",
            max_bytes=_MAX_STATUS_JSON_BYTES,
        )
    )
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
    return result


def _transcript_status(root: AuthorizedRoot, citekey: str) -> str:
    base = f"{citekey}/derived/transcription"
    try:
        directory_state = root.state(base)
        if directory_state == "missing":
            return "not-transcribed"
        if directory_state != "directory":
            raise CollectionReconciliationError(
                "transcript path is not a directory"
            )
        required = tuple(
            f"{base}/{name}"
            for name in (
                "audit.json",
                "clean.json",
                "clean.txt",
                "manifest.json",
            )
        )
        states = tuple(root.state(path) for path in required)
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    if any(state == "directory" for state in states):
        raise CollectionReconciliationError(
            "transcript artifact is not a regular file"
        )
    present = tuple(state == "regular" for state in states)
    if not any(present):
        return "not-transcribed"
    if not all(present):
        return "partial-transcript-artifacts"
    manifest = _read_bounded_json(root, f"{base}/manifest.json")
    audit = _read_bounded_json(root, f"{base}/audit.json")
    if (
        manifest.get("status") == "automated_unreviewed"
        and audit.get("status") == "passed"
    ):
        return "automated-unreviewed-with-recorded-passing-audit"
    return "transcript-present-status-unverified"


def _read_bounded_json(
    root: AuthorizedRoot,
    relative: str,
) -> dict[str, Any]:
    try:
        content = root.read_bytes(relative, max_bytes=_MAX_STATUS_JSON_BYTES)
    except PathSafetyError as error:
        raise CollectionReconciliationError(str(error)) from error
    if not content:
        raise CollectionReconciliationError(
            f"processing status JSON is empty: {Path(relative).name}"
        )
    data = json.loads(content.decode("utf-8"))
    if not isinstance(data, dict):
        raise CollectionReconciliationError(
            f"processing status JSON must be an object: {Path(relative).name}"
        )
    return data


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


def _pdf_expectation(record: ReferenceRecord) -> PdfExpectation:
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


def _source_type(record: ReferenceRecord) -> str:
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
            record.ingestion_status == "raw-extraction-present"
            for record in references
        ),
        "seed_transcripts_with_recorded_passing_audit": sum(
            record.transcript_status
            == "automated-unreviewed-with-recorded-passing-audit"
            for record in references
        ),
        "extra_raw_extractions": sum(
            extra.ingestion_status == "raw-extraction-present"
            for extra in extras
        ),
        "extra_transcripts_with_recorded_passing_audit": sum(
            extra.transcript_status
            == "automated-unreviewed-with-recorded-passing-audit"
            for extra in extras
        ),
        "duplicate_content_groups": len(
            {
                tuple(sorted((record.citekey, *record.duplicate_citekeys)))
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
            else _pretty_json(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "status": "not-supplied",
                    "source_revision": manifest.source_revision,
                }
            ).encode("utf-8")
        ),
        "coverage-observation.json": (
            coverage_observation.to_json().encode("utf-8")
            if coverage_observation is not None
            else _pretty_json(
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
        "citekey",
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
                "citekey": record.citekey,
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
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(canonical).hexdigest()}"


def _pretty_json(payload: object) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
