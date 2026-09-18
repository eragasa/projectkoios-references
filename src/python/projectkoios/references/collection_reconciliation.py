from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from projectkoios.references.models import ReferenceRecord

_SCHEMA_VERSION = 1
_PROCESSOR_VERSION = "0.4.0"
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
_VALID_CITEKEY = re.compile(r"^[^\s#%'(),={}\[\]]+$")
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
    with path.open(encoding="utf-8", newline="") as stream:
        rows = tuple(csv.DictReader(stream))
    if len(rows) > _MAX_RECORDS:
        raise CollectionReconciliationError("collection rows exceed hard limit")
    result: dict[str, CollectionRowEvidence] = {}
    for row in rows:
        citekey = (row.get("citekey") or "").strip()
        if not citekey:
            raise CollectionReconciliationError(
                "collection row has an empty citekey"
            )
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
    if directory.is_symlink() or not directory.is_dir():
        raise CollectionReconciliationError(
            "managed PDF root must be a real directory"
        )
    historical = _load_source_discovery(source_discovery)
    pdfs: list[ManagedPdf] = []
    for path in sorted(directory.glob("*.pdf"), key=lambda item: item.name):
        if not path.is_file() or path.is_symlink():
            continue
        byte_size = path.stat().st_size
        if byte_size <= 0 or byte_size > _MAX_PDF_BYTES:
            raise CollectionReconciliationError(
                f"managed PDF size is outside bounds: {path.name}"
            )
        digest = _hash_pdf(path)
        discovery = historical.get(path.stem)
        if discovery is not None and discovery[0] == digest:
            verified = True
            evidence = discovery[1]
        else:
            verified = False
            evidence = ()
        pdfs.append(
            ManagedPdf(
                filename=path.name,
                citekey=path.stem,
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
    if ingestion_root.is_symlink() or not ingestion_root.is_dir():
        raise CollectionReconciliationError(
            "ingestion root must be a real directory"
        )
    result: dict[str, ProcessingEvidence] = {}
    for citekey in sorted(set(citekeys)):
        if _VALID_CITEKEY.fullmatch(citekey) is None:
            raise CollectionReconciliationError(
                f"unsafe citekey for processing lookup: {citekey}"
            )
        source_directory = ingestion_root / citekey
        if source_directory.is_symlink():
            raise CollectionReconciliationError(
                f"processing directory must not be a symlink: {citekey}"
            )
        extraction = source_directory / "extraction.json"
        ingestion_status = (
            "raw-extraction-present"
            if _is_regular_file(extraction)
            else "not-ingested"
        )
        transcript_directory = source_directory / "derived" / "transcription"
        transcript_status = _transcript_status(transcript_directory)
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
    source_files = tuple(
        sorted(
            path
            for path in manuscript_root.rglob("*.tex")
            if path.is_file() and not path.is_symlink()
        )
    )
    if len(source_files) > _MAX_TEX_FILES:
        raise CollectionReconciliationError("TeX source count exceeds limit")
    total_bytes = sum(path.stat().st_size for path in source_files)
    if total_bytes > _MAX_TEX_BYTES:
        raise CollectionReconciliationError("TeX source bytes exceed limit")

    uses: dict[str, set[str]] = defaultdict(set)
    nocite_all = False
    relative_files: list[str] = []
    for path in source_files:
        relative = path.relative_to(manuscript_root).as_posix()
        relative_files.append(relative)
        text = path.read_text(encoding="utf-8")
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
                if _VALID_CITEKEY.fullmatch(key) is None:
                    continue
                uses[key].add(relative)

    bibliography = set(bibliography_keys)
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
    ordered_records = tuple(sorted(records, key=lambda item: item.citekey))
    citekeys = tuple(record.citekey for record in ordered_records)
    if len(citekeys) != len(set(citekeys)):
        raise CollectionReconciliationError(
            "bibliography contains duplicate citekeys"
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
        if matched_pdf is not None:
            status = (
                PdfStatus.MANAGED_VERIFIED
                if matched_pdf.historically_verified
                else PdfStatus.MANAGED_PRESENT
            )
            next_action = (
                "verify-bibliographic-metadata-and-rights"
                if matched_pdf.historically_verified
                else "review-pdf-identity-rights-and-record-acquisition"
            )
        elif expectation is PdfExpectation.EXPECTED:
            status = PdfStatus.NOT_LOCATED
            next_action = "search-authorized-roots-or-record-access-status"
        elif expectation is PdfExpectation.NOT_APPLICABLE:
            status = PdfStatus.PDF_NOT_APPLICABLE
            next_action = "verify-non-pdf-source-locator"
        else:
            status = PdfStatus.PDF_APPLICABILITY_REVIEW
            next_action = "decide-whether-a-pdf-is-applicable"
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
                    else ()
                ),
                duplicate_citekeys=duplicate_citekeys,
                access_status=(
                    "managed-local-access"
                    if matched_pdf is not None
                    else "not-assessed"
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
    coverage = (
        "preserved-bibliography-snapshot",
        "collection-row-evidence",
        "managed-pdf-directory-only",
        "privacy-reduced-source-discovery",
        (
            "existing-ingestion-and-transcript-state"
            if processing_supplied
            else "ingestion-and-transcript-state-not-supplied"
        ),
        (
            "isolated-manuscript-citation-closure"
            if citation_closure is not None
            else "citation-closure-not-supplied"
        ),
        "no-additional-filesystem-or-cloud-roots-scanned",
    )
    bibliography_sha256 = hashlib.sha256(bibliography_bytes).hexdigest()
    manifest_payload = {
        "schema_version": _SCHEMA_VERSION,
        "processor_version": _PROCESSOR_VERSION,
        "collection_id": collection_id,
        "source_revision": source_revision,
        "bibliography_sha256": bibliography_sha256,
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
        coverage=coverage,
        references=tuple(references),
        extra_pdfs=extras,
        counts=counts,
        manifest_id=_stable_id("collection-manifest", manifest_payload),
    )
    rendered = _render_outputs(manifest, citation_closure)
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
    if output_directory.is_symlink():
        raise CollectionReconciliationError(
            "output directory must not be a symlink"
        )
    if output_directory.exists():
        actual_names = {
            path.name
            for path in output_directory.iterdir()
            if path.is_file() and not path.is_symlink()
        }
        if actual_names != set(expected):
            raise CollectionReconciliationError(
                "existing reconciliation output is incomplete or unexpected"
            )
        for name, content in expected.items():
            path = output_directory / name
            if path.is_symlink() or path.read_bytes() != content:
                raise CollectionReconciliationError(
                    "existing reconciliation output differs"
                )
        return PublicationResult(
            status="unchanged",
            output_directory=output_directory,
            manifest_id=outputs.manifest.manifest_id,
        )

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.",
            dir=output_directory.parent,
        )
    )
    try:
        for name, content in expected.items():
            path = temporary / name
            with path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, output_directory)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return PublicationResult(
        status="created",
        output_directory=output_directory,
        manifest_id=outputs.manifest.manifest_id,
    )


def _load_source_discovery(
    path: Path | None,
) -> dict[str, tuple[str, tuple[str, ...]]]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
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
        if citekey in result:
            raise CollectionReconciliationError(
                f"duplicate source-discovery citekey: {citekey}"
            )
        result[citekey] = (digest, (basis,))
    return result


def _is_regular_file(path: Path) -> bool:
    if path.is_symlink():
        raise CollectionReconciliationError(
            f"processing evidence must not be a symlink: {path.name}"
        )
    return path.is_file()


def _transcript_status(directory: Path) -> str:
    if directory.is_symlink():
        raise CollectionReconciliationError(
            "transcript directory must not be a symlink"
        )
    required = tuple(
        directory / name
        for name in ("audit.json", "clean.json", "clean.txt", "manifest.json")
    )
    present = tuple(_is_regular_file(path) for path in required)
    if not any(present):
        return "not-transcribed"
    if not all(present):
        return "partial-transcript-artifacts"
    manifest = _read_bounded_json(directory / "manifest.json")
    audit = _read_bounded_json(directory / "audit.json")
    if (
        manifest.get("status") == "automated_unreviewed"
        and audit.get("status") == "passed"
    ):
        return "automated-unreviewed-with-recorded-passing-audit"
    return "transcript-present-status-unverified"


def _read_bounded_json(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    if size <= 0 or size > _MAX_STATUS_JSON_BYTES:
        raise CollectionReconciliationError(
            f"processing status JSON size is outside bounds: {path.name}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CollectionReconciliationError(
            f"processing status JSON must be an object: {path.name}"
        )
    return data


def _hash_pdf(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(5)
        if header != b"%PDF-":
            raise CollectionReconciliationError(
                f"managed file lacks PDF header: {path.name}"
            )
        digest.update(header)
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
        "pdf_applicability_review": sum(
            record.pdf_expectation is PdfExpectation.REVIEW
            and record.managed_pdf is None
            for record in references
        ),
        "pdf_not_applicable": sum(
            record.pdf_expectation is PdfExpectation.NOT_APPLICABLE
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
