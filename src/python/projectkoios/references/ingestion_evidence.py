from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from projectkoios.references.collection_reconciliation import (
    EvidenceMapping,
    ManagedPdf,
    ProcessingEvidence,
)
from projectkoios.references.path_safety import (
    CloudPlaceholderProbe,
    PathSafetyError,
    RootPreflightEvidence,
    RootStorageClass,
    authorize_root_preflight,
    read_path_bytes,
    validate_citekey,
)
from projectkoios.references.reconciliation_package import (
    ContentEvidence,
    canonical_json_bytes,
)

REFERENCE_EVIDENCE_CONTRACT_ID = "projectkoios.ingestion.reference-evidence"
REFERENCE_EVIDENCE_CONTRACT_VERSION = "0.1.0"
REFERENCE_EVIDENCE_CONTRACT_STATUS = "proposed"
REFERENCE_EVIDENCE_SCHEMA_VERSION = 1
REFERENCE_EVIDENCE_GENERATOR_NAME = "projectkoios-ingestion-reference-evidence"
REFERENCE_EVIDENCE_GENERATOR_VERSION = "1"
REFERENCE_EVIDENCE_TRANSCRIPT_GENERATION = 1
REFERENCE_EVIDENCE_MEDIA_TYPE = (
    "application/vnd.projectkoios.ingestion.reference-evidence+json"
)
REFERENCE_EVIDENCE_MAX_BYTES = 262_144
REFERENCE_EVIDENCE_MAX_INPUTS = 10_000
REFERENCE_EVIDENCE_MAX_LINEAGE_IDS = 4_096
REFERENCE_EVIDENCE_MAX_LAYOUT_IDS = 512
REFERENCE_EVIDENCE_MAX_LAYER_COUNTS = 32
REFERENCE_EVIDENCE_MAX_LIMITATIONS = 32
REFERENCE_EVIDENCE_ADAPTER_VERSION = "1"

_MAX_BOUND_ARTIFACT_BYTES = 128_000_000
_MAX_JSON_DEPTH = 64
_MAX_STRING_CHARACTERS = 4_096
_EXTRACTION_CONTRACT_VERSION = "2.2"
_TRANSCRIPT_CONTRACT_VERSION = "1.0"
_DERIVATION_AUDIT_CONTRACT_VERSION = "1.0"
_SOURCE_MEDIA_TYPE = "application/pdf"
_EXTRACTION_MEDIA_TYPE = (
    "application/vnd.projectkoios.ingestion.extraction+json"
)
_TRANSCRIPT_MEDIA_TYPE = (
    "application/vnd.projectkoios.ingestion.clean-transcript+json"
)
_AUDIT_MEDIA_TYPE = (
    "application/vnd.projectkoios.ingestion.derivation-audit+json"
)
_REQUIRED_LIMITATIONS = frozenset(
    {
        "automated_unreviewed",
        "not_extraction_accuracy_verification",
        "not_human_proofread",
        "not_independent_revalidation",
        "not_producer_authentication",
        "not_publication_suitable",
        "not_scientifically_validated",
        "not_semantically_corrected",
    }
)
_REQUIRED_AUDIT_COUNTS = {
    "clean_transcript_artifacts": 1,
    "extraction_result": 1,
    "transcription_results": 1,
}


class IngestionEvidenceError(ValueError):
    """Base error for the strict references-owned evidence consumer."""


class IngestionEvidenceLimitError(IngestionEvidenceError):
    """Raised before untrusted evidence exceeds a deterministic bound."""


class IngestionEvidenceParseError(IngestionEvidenceError):
    """Raised when producer bytes are malformed or unsupported."""


class IngestionEvidenceVerificationError(IngestionEvidenceError):
    """Raised when producer evidence does not match a managed PDF."""


@dataclass(frozen=True)
class ReferenceEvidenceArtifact:
    media_type: str
    sha256: str
    byte_length: int


@dataclass(frozen=True)
class ReferenceEvidenceSource:
    blob_id: str
    hash_algorithm: str
    content_sha256: str
    byte_length: int
    media_type: str


@dataclass(frozen=True)
class ReferenceEvidenceExtraction:
    artifact: ReferenceEvidenceArtifact
    contract_version: str
    manifest_id: str
    document_id: str
    status: str
    extractor_name: str
    extractor_version: str
    configuration_digest: str
    warning_count: int


@dataclass(frozen=True)
class ReferenceEvidenceTranscript:
    artifact: ReferenceEvidenceArtifact
    artifact_generation: int
    contract_version: str
    artifact_id: str
    status: str
    structured_transcription_result_id: str
    layout_result_ids: tuple[str, ...]
    text_sha256: str
    text_utf8_byte_length: int
    processor_name: str
    processor_version: str
    configuration_digest: str
    warning_count: int


@dataclass(frozen=True)
class ReferenceEvidenceLayerCount:
    layer: str
    count: int


@dataclass(frozen=True)
class ReferenceEvidenceAudit:
    artifact: ReferenceEvidenceArtifact
    contract_version: str
    report_id: str
    status: str
    scope: str
    independently_revalidated: bool
    processor_name: str
    processor_version: str
    audited_artifact_ids: tuple[str, ...]
    audited_layer_counts: tuple[ReferenceEvidenceLayerCount, ...]
    finding_count: int


@dataclass(frozen=True)
class ReferenceEvidenceRecord:
    record_id: str
    contract_id: str
    contract_version: str
    contract_status: str
    schema_version: int
    media_type: str
    generator_name: str
    generator_version: str
    completeness: str
    completeness_reasons: tuple[str, ...]
    source: ReferenceEvidenceSource
    extraction: ReferenceEvidenceExtraction
    transcript: ReferenceEvidenceTranscript
    derivation_audit: ReferenceEvidenceAudit
    limitations: tuple[str, ...]

    def to_bytes(self) -> bytes:
        return _canonical_json_bytes(asdict(self))


@dataclass(frozen=True)
class ReferenceEvidenceInput:
    citekey: str
    path: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = None

    def __post_init__(self) -> None:
        validate_citekey(self.citekey, field="reference-evidence citekey")
        if not isinstance(self.path, Path):
            raise TypeError("reference-evidence path must be a Path")
        if not isinstance(self.storage_class, RootStorageClass):
            raise TypeError("reference-evidence storage class must be explicit")


def parse_reference_evidence(content: bytes) -> ReferenceEvidenceRecord:
    """Parse canonical bytes under the Proposed generation-1 contract."""

    value = _parse_json_bytes(content)
    try:
        canonical = _canonical_json_bytes(value)
    except (TypeError, UnicodeEncodeError, ValueError, RecursionError) as error:
        raise IngestionEvidenceParseError(
            "reference evidence cannot be canonicalized"
        ) from error
    if canonical != content:
        raise IngestionEvidenceParseError(
            "reference evidence is not canonical JSON"
        )
    try:
        record = _decode_record(value)
        _validate_record(record)
    except IngestionEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise IngestionEvidenceParseError(
            f"reference evidence is invalid: {error}"
        ) from error
    if record.to_bytes() != content:
        raise IngestionEvidenceParseError(
            "reference evidence replay differs from producer bytes"
        )
    return record


def verify_reference_evidence_source(
    record: ReferenceEvidenceRecord,
    *,
    source_sha256: str,
    source_byte_length: int,
    source_media_type: str = _SOURCE_MEDIA_TYPE,
) -> None:
    """Verify source identity without claiming independent derivation review."""

    if not isinstance(record, ReferenceEvidenceRecord):
        raise TypeError("record must be ReferenceEvidenceRecord")
    reparsed = parse_reference_evidence(record.to_bytes())
    if reparsed != record:
        raise IngestionEvidenceVerificationError(
            "reference evidence object differs from canonical replay"
        )
    digest = _sha256(source_sha256, "expected source_sha256")
    byte_length = _nonnegative_int(
        source_byte_length, "expected source_byte_length"
    )
    media_type = _text(source_media_type, "expected source_media_type")
    source = record.source
    if (
        source.content_sha256 != digest
        or source.byte_length != byte_length
        or source.media_type != media_type
        or source.blob_id != f"blob:sha256:{digest}"
    ):
        raise IngestionEvidenceVerificationError(
            "reference evidence does not match the managed PDF identity"
        )


def load_ingestion_reference_evidence(
    inputs: Iterable[ReferenceEvidenceInput],
    *,
    managed_pdfs: Sequence[ManagedPdf],
) -> EvidenceMapping[ProcessingEvidence]:
    """Load injected evidence and bind it to managed PDF identities."""

    bindings = tuple(inputs)
    if len(bindings) > REFERENCE_EVIDENCE_MAX_INPUTS:
        raise IngestionEvidenceLimitError(
            "reference-evidence inputs exceed the item limit"
        )
    if any(not isinstance(item, ReferenceEvidenceInput) for item in bindings):
        raise TypeError(
            "reference-evidence inputs must be ReferenceEvidenceInput values"
        )
    managed_by_citekey = {item.citekey: item for item in managed_pdfs}
    if len(managed_by_citekey) != len(managed_pdfs):
        raise IngestionEvidenceVerificationError(
            "managed PDFs contain duplicate citekeys"
        )
    result: dict[str, ProcessingEvidence] = {}
    record_ids: set[str] = set()
    retained: list[ContentEvidence] = []
    root_preflights: list[RootPreflightEvidence] = []
    for binding in sorted(bindings, key=lambda item: item.citekey):
        if binding.citekey in result:
            raise IngestionEvidenceVerificationError(
                f"duplicate reference-evidence citekey: {binding.citekey}"
            )
        managed = managed_by_citekey.get(binding.citekey)
        if managed is None:
            raise IngestionEvidenceVerificationError(
                "reference evidence has no matching managed PDF: "
                f"{binding.citekey}"
            )
        root_preflights.append(
            authorize_root_preflight(
                root_alias=f"reference-evidence-{binding.citekey}",
                storage_class=binding.storage_class,
                placeholder_probe=binding.placeholder_probe,
            )
        )
        try:
            content = read_path_bytes(
                binding.path,
                label=f"reference evidence for {binding.citekey}",
                root_alias=f"reference-evidence-{binding.citekey}",
                storage_class=binding.storage_class,
                placeholder_probe=binding.placeholder_probe,
                max_bytes=REFERENCE_EVIDENCE_MAX_BYTES,
            )
        except PathSafetyError as error:
            raise IngestionEvidenceVerificationError(str(error)) from error
        record = parse_reference_evidence(content)
        if record.record_id in record_ids:
            raise IngestionEvidenceVerificationError(
                f"duplicate reference-evidence record: {record.record_id}"
            )
        verify_reference_evidence_source(
            record,
            source_sha256=managed.sha256,
            source_byte_length=managed.byte_size,
            source_media_type=_SOURCE_MEDIA_TYPE,
        )
        record_ids.add(record.record_id)
        result[binding.citekey] = ProcessingEvidence._from_reference_evidence(
            evidence_record_id=record.record_id,
            contract_status=record.contract_status,
            derivation_audit_status="recorded-passing",
            derivation_audit_scope=record.derivation_audit.scope,
            independently_revalidated=(
                record.derivation_audit.independently_revalidated
            ),
        )
        retained.append(
            ContentEvidence.from_bytes(
                role="ingestion-reference-evidence",
                filename=(
                    "inputs/ingestion-reference-evidence/"
                    f"{binding.citekey}.json"
                ),
                content=content,
            )
        )
    observation = canonical_json_bytes(
        {
            "adapter_version": REFERENCE_EVIDENCE_ADAPTER_VERSION,
            "contract_status": REFERENCE_EVIDENCE_CONTRACT_STATUS,
            "records": result,
        }
    )
    retained.append(
        ContentEvidence.from_bytes(
            role="processing-observation",
            filename="inputs/processing-observation.json",
            content=observation,
        )
    )
    return EvidenceMapping(
        entries=tuple(sorted(result.items())),
        input_evidence=tuple(sorted(retained, key=_content_evidence_key)),
        root_preflights=tuple(root_preflights),
    )


def _parse_json_bytes(content: bytes) -> object:
    if not isinstance(content, bytes):
        raise TypeError("reference evidence must be bytes")
    if len(content) > REFERENCE_EVIDENCE_MAX_BYTES:
        raise IngestionEvidenceLimitError(
            "reference evidence exceeds the size limit"
        )
    try:
        text = content.decode("utf-8", errors="strict")
        _require_bounded_json_nesting(text)
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except IngestionEvidenceError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise IngestionEvidenceParseError(
            f"reference evidence is malformed JSON: {error}"
        ) from error


def _decode_record(value: object) -> ReferenceEvidenceRecord:
    root = _mapping(
        value,
        "reference evidence",
        {
            "record_id",
            "contract_id",
            "contract_version",
            "contract_status",
            "schema_version",
            "media_type",
            "generator_name",
            "generator_version",
            "completeness",
            "completeness_reasons",
            "source",
            "extraction",
            "transcript",
            "derivation_audit",
            "limitations",
        },
    )
    source = _mapping(
        root["source"],
        "source",
        {
            "blob_id",
            "hash_algorithm",
            "content_sha256",
            "byte_length",
            "media_type",
        },
    )
    extraction = _mapping(
        root["extraction"],
        "extraction",
        {
            "artifact",
            "contract_version",
            "manifest_id",
            "document_id",
            "status",
            "extractor_name",
            "extractor_version",
            "configuration_digest",
            "warning_count",
        },
    )
    transcript = _mapping(
        root["transcript"],
        "transcript",
        {
            "artifact",
            "artifact_generation",
            "contract_version",
            "artifact_id",
            "status",
            "structured_transcription_result_id",
            "layout_result_ids",
            "text_sha256",
            "text_utf8_byte_length",
            "processor_name",
            "processor_version",
            "configuration_digest",
            "warning_count",
        },
    )
    audit = _mapping(
        root["derivation_audit"],
        "derivation_audit",
        {
            "artifact",
            "contract_version",
            "report_id",
            "status",
            "scope",
            "independently_revalidated",
            "processor_name",
            "processor_version",
            "audited_artifact_ids",
            "audited_layer_counts",
            "finding_count",
        },
    )
    return ReferenceEvidenceRecord(
        record_id=_text(root["record_id"], "record_id"),
        contract_id=_text(root["contract_id"], "contract_id"),
        contract_version=_text(root["contract_version"], "contract_version"),
        contract_status=_text(root["contract_status"], "contract_status"),
        schema_version=_nonnegative_int(
            root["schema_version"], "schema_version"
        ),
        media_type=_text(root["media_type"], "media_type"),
        generator_name=_text(root["generator_name"], "generator_name"),
        generator_version=_text(root["generator_version"], "generator_version"),
        completeness=_text(root["completeness"], "completeness"),
        completeness_reasons=_string_tuple(
            root["completeness_reasons"],
            "completeness_reasons",
            REFERENCE_EVIDENCE_MAX_LIMITATIONS,
        ),
        source=ReferenceEvidenceSource(
            blob_id=_text(source["blob_id"], "source.blob_id"),
            hash_algorithm=_text(
                source["hash_algorithm"], "source.hash_algorithm"
            ),
            content_sha256=_sha256(
                source["content_sha256"], "source.content_sha256"
            ),
            byte_length=_nonnegative_int(
                source["byte_length"], "source.byte_length"
            ),
            media_type=_text(source["media_type"], "source.media_type"),
        ),
        extraction=ReferenceEvidenceExtraction(
            artifact=_decode_artifact(
                extraction["artifact"], "extraction.artifact"
            ),
            contract_version=_text(
                extraction["contract_version"], "extraction.contract_version"
            ),
            manifest_id=_text(
                extraction["manifest_id"], "extraction.manifest_id"
            ),
            document_id=_text(
                extraction["document_id"], "extraction.document_id"
            ),
            status=_text(extraction["status"], "extraction.status"),
            extractor_name=_text(
                extraction["extractor_name"], "extraction.extractor_name"
            ),
            extractor_version=_text(
                extraction["extractor_version"],
                "extraction.extractor_version",
            ),
            configuration_digest=_text(
                extraction["configuration_digest"],
                "extraction.configuration_digest",
            ),
            warning_count=_nonnegative_int(
                extraction["warning_count"], "extraction.warning_count"
            ),
        ),
        transcript=ReferenceEvidenceTranscript(
            artifact=_decode_artifact(
                transcript["artifact"], "transcript.artifact"
            ),
            artifact_generation=_nonnegative_int(
                transcript["artifact_generation"],
                "transcript.artifact_generation",
            ),
            contract_version=_text(
                transcript["contract_version"], "transcript.contract_version"
            ),
            artifact_id=_text(
                transcript["artifact_id"], "transcript.artifact_id"
            ),
            status=_text(transcript["status"], "transcript.status"),
            structured_transcription_result_id=_text(
                transcript["structured_transcription_result_id"],
                "transcript.structured_transcription_result_id",
            ),
            layout_result_ids=_string_tuple(
                transcript["layout_result_ids"],
                "transcript.layout_result_ids",
                REFERENCE_EVIDENCE_MAX_LAYOUT_IDS,
            ),
            text_sha256=_sha256(
                transcript["text_sha256"], "transcript.text_sha256"
            ),
            text_utf8_byte_length=_nonnegative_int(
                transcript["text_utf8_byte_length"],
                "transcript.text_utf8_byte_length",
            ),
            processor_name=_text(
                transcript["processor_name"], "transcript.processor_name"
            ),
            processor_version=_text(
                transcript["processor_version"],
                "transcript.processor_version",
            ),
            configuration_digest=_text(
                transcript["configuration_digest"],
                "transcript.configuration_digest",
            ),
            warning_count=_nonnegative_int(
                transcript["warning_count"], "transcript.warning_count"
            ),
        ),
        derivation_audit=ReferenceEvidenceAudit(
            artifact=_decode_artifact(
                audit["artifact"], "derivation_audit.artifact"
            ),
            contract_version=_text(
                audit["contract_version"],
                "derivation_audit.contract_version",
            ),
            report_id=_text(audit["report_id"], "derivation_audit.report_id"),
            status=_text(audit["status"], "derivation_audit.status"),
            scope=_text(audit["scope"], "derivation_audit.scope"),
            independently_revalidated=_boolean(
                audit["independently_revalidated"],
                "derivation_audit.independently_revalidated",
            ),
            processor_name=_text(
                audit["processor_name"], "derivation_audit.processor_name"
            ),
            processor_version=_text(
                audit["processor_version"],
                "derivation_audit.processor_version",
            ),
            audited_artifact_ids=_string_tuple(
                audit["audited_artifact_ids"],
                "derivation_audit.audited_artifact_ids",
                REFERENCE_EVIDENCE_MAX_LINEAGE_IDS,
            ),
            audited_layer_counts=_decode_layer_counts(
                audit["audited_layer_counts"]
            ),
            finding_count=_nonnegative_int(
                audit["finding_count"], "derivation_audit.finding_count"
            ),
        ),
        limitations=_string_tuple(
            root["limitations"],
            "limitations",
            REFERENCE_EVIDENCE_MAX_LIMITATIONS,
        ),
    )


def _validate_record(record: ReferenceEvidenceRecord) -> None:
    expected_constants = (
        (record.contract_id, REFERENCE_EVIDENCE_CONTRACT_ID, "contract ID"),
        (
            record.contract_version,
            REFERENCE_EVIDENCE_CONTRACT_VERSION,
            "contract version",
        ),
        (
            record.contract_status,
            REFERENCE_EVIDENCE_CONTRACT_STATUS,
            "contract status",
        ),
        (
            record.schema_version,
            REFERENCE_EVIDENCE_SCHEMA_VERSION,
            "schema version",
        ),
        (record.media_type, REFERENCE_EVIDENCE_MEDIA_TYPE, "media type"),
        (
            record.generator_name,
            REFERENCE_EVIDENCE_GENERATOR_NAME,
            "generator name",
        ),
        (
            record.generator_version,
            REFERENCE_EVIDENCE_GENERATOR_VERSION,
            "generator version",
        ),
    )
    for actual, expected, label in expected_constants:
        if actual != expected:
            raise ValueError(f"unsupported reference-evidence {label}")
    if record.completeness != "complete":
        raise IngestionEvidenceVerificationError(
            f"reference evidence is not complete: {record.completeness}"
        )
    if record.completeness_reasons:
        raise ValueError("complete reference evidence has failure reasons")
    if tuple(sorted(record.limitations)) != record.limitations:
        raise ValueError("reference-evidence limitations are not sorted")
    if not _REQUIRED_LIMITATIONS <= set(record.limitations):
        raise ValueError("reference-evidence limitations are incomplete")

    source = record.source
    if source.hash_algorithm != "sha256":
        raise ValueError("unsupported source hash algorithm")
    if source.blob_id != f"blob:sha256:{source.content_sha256}":
        raise ValueError("source blob ID differs from source SHA-256")
    if source.media_type != _SOURCE_MEDIA_TYPE:
        raise ValueError("unsupported source media type")

    extraction = record.extraction
    _require_artifact_media(
        extraction.artifact, _EXTRACTION_MEDIA_TYPE, "extraction"
    )
    if extraction.contract_version != _EXTRACTION_CONTRACT_VERSION:
        raise ValueError("unsupported extraction contract version")
    if extraction.status != "completed":
        raise ValueError("complete evidence requires completed extraction")

    transcript = record.transcript
    _require_artifact_media(
        transcript.artifact, _TRANSCRIPT_MEDIA_TYPE, "transcript"
    )
    if (
        transcript.artifact_generation
        != REFERENCE_EVIDENCE_TRANSCRIPT_GENERATION
    ):
        raise ValueError("unsupported transcript artifact generation")
    if transcript.contract_version != _TRANSCRIPT_CONTRACT_VERSION:
        raise ValueError("unsupported clean-transcript contract version")
    if transcript.status != "automated_unreviewed":
        raise ValueError(
            "complete evidence requires automated-unreviewed transcript status"
        )
    if not transcript.layout_result_ids:
        raise ValueError("transcript layout lineage is empty")
    if len(set(transcript.layout_result_ids)) != len(
        transcript.layout_result_ids
    ):
        raise ValueError("transcript layout lineage contains duplicates")

    audit = record.derivation_audit
    _require_artifact_media(audit.artifact, _AUDIT_MEDIA_TYPE, "audit")
    if audit.contract_version != _DERIVATION_AUDIT_CONTRACT_VERSION:
        raise ValueError("unsupported derivation-audit contract version")
    if audit.status != "passed":
        raise ValueError("complete evidence requires a recorded passing audit")
    if audit.scope != "recorded_producer_derivation_audit":
        raise ValueError("unsupported derivation-audit scope")
    if audit.independently_revalidated is not False:
        raise ValueError(
            "producer evidence cannot claim independent revalidation"
        )
    if audit.finding_count != 0:
        raise ValueError("passing derivation audit contains findings")
    if not audit.audited_artifact_ids:
        raise ValueError("derivation-audit lineage is empty")
    if len(set(audit.audited_artifact_ids)) != len(audit.audited_artifact_ids):
        raise ValueError("derivation-audit lineage contains duplicates")
    layers = tuple(item.layer for item in audit.audited_layer_counts)
    if tuple(sorted(layers)) != layers or len(set(layers)) != len(layers):
        raise ValueError("derivation-audit layer counts are not unique/sorted")
    counts = {item.layer: item.count for item in audit.audited_layer_counts}
    if any(
        counts.get(layer) != count
        for layer, count in _REQUIRED_AUDIT_COUNTS.items()
    ):
        raise ValueError("derivation-audit layer coverage is incomplete")
    if counts.get("layout_results") != len(transcript.layout_result_ids):
        raise ValueError("derivation-audit layout coverage is incomplete")
    required_ids = {
        extraction.manifest_id,
        extraction.document_id,
        transcript.artifact_id,
        transcript.structured_transcription_result_id,
        *transcript.layout_result_ids,
    }
    if not required_ids <= set(audit.audited_artifact_ids):
        raise ValueError("derivation-audit lineage is incomplete")

    payload = asdict(record)
    record_id = payload.pop("record_id")
    expected_id = _stable_id("reference-evidence-record", payload)
    if record_id != expected_id:
        raise ValueError("reference-evidence record ID is inconsistent")


def _decode_artifact(value: object, name: str) -> ReferenceEvidenceArtifact:
    item = _mapping(value, name, {"media_type", "sha256", "byte_length"})
    byte_length = _nonnegative_int(item["byte_length"], f"{name}.byte_length")
    if byte_length > _MAX_BOUND_ARTIFACT_BYTES:
        raise IngestionEvidenceLimitError(f"{name} exceeds the byte limit")
    return ReferenceEvidenceArtifact(
        media_type=_text(item["media_type"], f"{name}.media_type"),
        sha256=_sha256(item["sha256"], f"{name}.sha256"),
        byte_length=byte_length,
    )


def _decode_layer_counts(
    value: object,
) -> tuple[ReferenceEvidenceLayerCount, ...]:
    values = _list(
        value,
        "derivation_audit.audited_layer_counts",
        REFERENCE_EVIDENCE_MAX_LAYER_COUNTS,
    )
    result: list[ReferenceEvidenceLayerCount] = []
    for index, value_item in enumerate(values):
        name = f"derivation_audit.audited_layer_counts[{index}]"
        item = _mapping(value_item, name, {"layer", "count"})
        result.append(
            ReferenceEvidenceLayerCount(
                layer=_text(item["layer"], f"{name}.layer"),
                count=_nonnegative_int(item["count"], f"{name}.count"),
            )
        )
    return tuple(result)


def _require_artifact_media(
    artifact: ReferenceEvidenceArtifact,
    expected: str,
    label: str,
) -> None:
    if artifact.media_type != expected:
        raise ValueError(f"unsupported {label} artifact media type")


def _mapping(value: object, name: str, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} field names must be strings")
    actual = set(value)
    unknown = actual - fields
    missing = fields - actual
    if unknown:
        raise ValueError(f"{name} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")
    return value


def _list(value: object, name: str, maximum: int) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    if len(value) > maximum:
        raise IngestionEvidenceLimitError(f"{name} exceeds the item limit")
    return value


def _string_tuple(value: object, name: str, maximum: int) -> tuple[str, ...]:
    return tuple(
        _text(item, f"{name}[{index}]")
        for index, item in enumerate(_list(value, name, maximum))
    )


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > _MAX_STRING_CHARACTERS:
        raise IngestionEvidenceLimitError(f"{name} exceeds the string limit")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must be valid UTF-8") from error
    return value


def _sha256(value: object, name: str) -> str:
    digest = _text(value, name)
    if len(digest) != 64 or digest != digest.lower():
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    try:
        int(digest, 16)
    except ValueError as error:
        raise ValueError(
            f"{name} must be a lowercase SHA-256 digest"
        ) from error
    return digest


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be boolean")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def _stable_id(namespace: str, value: object) -> str:
    content = _canonical_json_bytes([value])
    return f"{namespace}:sha256:{hashlib.sha256(content).hexdigest()}"


def _object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _require_bounded_json_nesting(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise IngestionEvidenceLimitError(
                    "reference-evidence JSON exceeds the depth limit"
                )
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise ValueError(
                    "reference-evidence JSON nesting is unbalanced"
                )
    if in_string or depth != 0:
        raise ValueError("reference-evidence JSON nesting is incomplete")


def _content_evidence_key(
    value: ContentEvidence,
) -> tuple[str, str, int, str]:
    return (value.role, value.filename, value.byte_size, value.sha256)
