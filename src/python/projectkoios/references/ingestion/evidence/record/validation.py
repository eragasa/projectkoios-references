from __future__ import annotations

from dataclasses import asdict

from ..artifact import ReferenceEvidenceArtifact
from ..contract import (
    REFERENCE_EVIDENCE_CONTRACT_ID,
    REFERENCE_EVIDENCE_CONTRACT_STATUS,
    REFERENCE_EVIDENCE_CONTRACT_VERSION,
    REFERENCE_EVIDENCE_GENERATOR_NAME,
    REFERENCE_EVIDENCE_GENERATOR_VERSION,
    REFERENCE_EVIDENCE_MEDIA_TYPE,
    REFERENCE_EVIDENCE_SCHEMA_VERSION,
    REFERENCE_EVIDENCE_TRANSCRIPT_GENERATION,
)
from ..error import IngestionEvidenceVerificationError
from ..media import (
    AUDIT_MEDIA_TYPE,
    EXTRACTION_MEDIA_TYPE,
    SOURCE_MEDIA_TYPE,
    TRANSCRIPT_MEDIA_TYPE,
)
from .aggregate import ReferenceEvidenceRecord
from .serialization import stable_reference_evidence_id

_EXTRACTION_CONTRACT_VERSION = "2.2"
_TRANSCRIPT_CONTRACT_VERSION = "1.0"
_DERIVATION_AUDIT_CONTRACT_VERSION = "1.0"
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


def validate_reference_evidence_record(record: ReferenceEvidenceRecord) -> None:
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
    if source.media_type != SOURCE_MEDIA_TYPE:
        raise ValueError("unsupported source media type")

    extraction = record.extraction
    require_artifact_media(
        extraction.artifact, EXTRACTION_MEDIA_TYPE, "extraction"
    )
    if extraction.contract_version != _EXTRACTION_CONTRACT_VERSION:
        raise ValueError("unsupported extraction contract version")
    if extraction.status != "completed":
        raise ValueError("complete evidence requires completed extraction")

    transcript = record.transcript
    require_artifact_media(
        transcript.artifact, TRANSCRIPT_MEDIA_TYPE, "transcript"
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
    require_artifact_media(audit.artifact, AUDIT_MEDIA_TYPE, "audit")
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
    expected_id = stable_reference_evidence_id(
        "reference-evidence-record", payload
    )
    if record_id != expected_id:
        raise ValueError("reference-evidence record ID is inconsistent")


def require_artifact_media(
    artifact: ReferenceEvidenceArtifact,
    expected: str,
    label: str,
) -> None:
    if artifact.media_type != expected:
        raise ValueError(f"unsupported {label} artifact media type")
