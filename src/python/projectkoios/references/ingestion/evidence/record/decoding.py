from __future__ import annotations

from ..artifact import ReferenceEvidenceArtifact
from ..audit import ReferenceEvidenceAudit
from ..contract import (
    REFERENCE_EVIDENCE_MAX_LAYER_COUNTS,
    REFERENCE_EVIDENCE_MAX_LAYOUT_IDS,
    REFERENCE_EVIDENCE_MAX_LIMITATIONS,
    REFERENCE_EVIDENCE_MAX_LINEAGE_IDS,
)
from ..error import IngestionEvidenceLimitError
from ..extraction import ReferenceEvidenceExtraction
from ..json.decoding import (
    require_boolean,
    require_list,
    require_mapping,
    require_nonnegative_int,
    require_sha256,
    require_string_tuple,
    require_text,
)
from ..layer.count import ReferenceEvidenceLayerCount
from ..source import ReferenceEvidenceSource
from ..transcript import ReferenceEvidenceTranscript
from .aggregate import ReferenceEvidenceRecord

_MAX_BOUND_ARTIFACT_BYTES = 128_000_000


def decode_reference_evidence_record(value: object) -> ReferenceEvidenceRecord:
    root = require_mapping(
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
    source = require_mapping(
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
    extraction = require_mapping(
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
    transcript = require_mapping(
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
    audit = require_mapping(
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
        record_id=require_text(root["record_id"], "record_id"),
        contract_id=require_text(root["contract_id"], "contract_id"),
        contract_version=require_text(
            root["contract_version"], "contract_version"
        ),
        contract_status=require_text(
            root["contract_status"], "contract_status"
        ),
        schema_version=require_nonnegative_int(
            root["schema_version"], "schema_version"
        ),
        media_type=require_text(root["media_type"], "media_type"),
        generator_name=require_text(root["generator_name"], "generator_name"),
        generator_version=require_text(
            root["generator_version"], "generator_version"
        ),
        completeness=require_text(root["completeness"], "completeness"),
        completeness_reasons=require_string_tuple(
            root["completeness_reasons"],
            "completeness_reasons",
            REFERENCE_EVIDENCE_MAX_LIMITATIONS,
        ),
        source=ReferenceEvidenceSource(
            blob_id=require_text(source["blob_id"], "source.blob_id"),
            hash_algorithm=require_text(
                source["hash_algorithm"], "source.hash_algorithm"
            ),
            content_sha256=require_sha256(
                source["content_sha256"], "source.content_sha256"
            ),
            byte_length=require_nonnegative_int(
                source["byte_length"], "source.byte_length"
            ),
            media_type=require_text(source["media_type"], "source.media_type"),
        ),
        extraction=ReferenceEvidenceExtraction(
            artifact=decode_reference_evidence_artifact(
                extraction["artifact"], "extraction.artifact"
            ),
            contract_version=require_text(
                extraction["contract_version"], "extraction.contract_version"
            ),
            manifest_id=require_text(
                extraction["manifest_id"], "extraction.manifest_id"
            ),
            document_id=require_text(
                extraction["document_id"], "extraction.document_id"
            ),
            status=require_text(extraction["status"], "extraction.status"),
            extractor_name=require_text(
                extraction["extractor_name"], "extraction.extractor_name"
            ),
            extractor_version=require_text(
                extraction["extractor_version"],
                "extraction.extractor_version",
            ),
            configuration_digest=require_text(
                extraction["configuration_digest"],
                "extraction.configuration_digest",
            ),
            warning_count=require_nonnegative_int(
                extraction["warning_count"], "extraction.warning_count"
            ),
        ),
        transcript=ReferenceEvidenceTranscript(
            artifact=decode_reference_evidence_artifact(
                transcript["artifact"], "transcript.artifact"
            ),
            artifact_generation=require_nonnegative_int(
                transcript["artifact_generation"],
                "transcript.artifact_generation",
            ),
            contract_version=require_text(
                transcript["contract_version"], "transcript.contract_version"
            ),
            artifact_id=require_text(
                transcript["artifact_id"], "transcript.artifact_id"
            ),
            status=require_text(transcript["status"], "transcript.status"),
            structured_transcription_result_id=require_text(
                transcript["structured_transcription_result_id"],
                "transcript.structured_transcription_result_id",
            ),
            layout_result_ids=require_string_tuple(
                transcript["layout_result_ids"],
                "transcript.layout_result_ids",
                REFERENCE_EVIDENCE_MAX_LAYOUT_IDS,
            ),
            text_sha256=require_sha256(
                transcript["text_sha256"], "transcript.text_sha256"
            ),
            text_utf8_byte_length=require_nonnegative_int(
                transcript["text_utf8_byte_length"],
                "transcript.text_utf8_byte_length",
            ),
            processor_name=require_text(
                transcript["processor_name"], "transcript.processor_name"
            ),
            processor_version=require_text(
                transcript["processor_version"],
                "transcript.processor_version",
            ),
            configuration_digest=require_text(
                transcript["configuration_digest"],
                "transcript.configuration_digest",
            ),
            warning_count=require_nonnegative_int(
                transcript["warning_count"], "transcript.warning_count"
            ),
        ),
        derivation_audit=ReferenceEvidenceAudit(
            artifact=decode_reference_evidence_artifact(
                audit["artifact"], "derivation_audit.artifact"
            ),
            contract_version=require_text(
                audit["contract_version"],
                "derivation_audit.contract_version",
            ),
            report_id=require_text(
                audit["report_id"], "derivation_audit.report_id"
            ),
            status=require_text(audit["status"], "derivation_audit.status"),
            scope=require_text(audit["scope"], "derivation_audit.scope"),
            independently_revalidated=require_boolean(
                audit["independently_revalidated"],
                "derivation_audit.independently_revalidated",
            ),
            processor_name=require_text(
                audit["processor_name"], "derivation_audit.processor_name"
            ),
            processor_version=require_text(
                audit["processor_version"],
                "derivation_audit.processor_version",
            ),
            audited_artifact_ids=require_string_tuple(
                audit["audited_artifact_ids"],
                "derivation_audit.audited_artifact_ids",
                REFERENCE_EVIDENCE_MAX_LINEAGE_IDS,
            ),
            audited_layer_counts=decode_reference_evidence_layer_counts(
                audit["audited_layer_counts"]
            ),
            finding_count=require_nonnegative_int(
                audit["finding_count"], "derivation_audit.finding_count"
            ),
        ),
        limitations=require_string_tuple(
            root["limitations"],
            "limitations",
            REFERENCE_EVIDENCE_MAX_LIMITATIONS,
        ),
    )


def decode_reference_evidence_artifact(
    value: object, name: str
) -> ReferenceEvidenceArtifact:
    item = require_mapping(value, name, {"media_type", "sha256", "byte_length"})
    byte_length = require_nonnegative_int(
        item["byte_length"], f"{name}.byte_length"
    )
    if byte_length > _MAX_BOUND_ARTIFACT_BYTES:
        raise IngestionEvidenceLimitError(f"{name} exceeds the byte limit")
    return ReferenceEvidenceArtifact(
        media_type=require_text(item["media_type"], f"{name}.media_type"),
        sha256=require_sha256(item["sha256"], f"{name}.sha256"),
        byte_length=byte_length,
    )


def decode_reference_evidence_layer_counts(
    value: object,
) -> tuple[ReferenceEvidenceLayerCount, ...]:
    values = require_list(
        value,
        "derivation_audit.audited_layer_counts",
        REFERENCE_EVIDENCE_MAX_LAYER_COUNTS,
    )
    result: list[ReferenceEvidenceLayerCount] = []
    for index, value_item in enumerate(values):
        name = f"derivation_audit.audited_layer_counts[{index}]"
        item = require_mapping(value_item, name, {"layer", "count"})
        result.append(
            ReferenceEvidenceLayerCount(
                layer=require_text(item["layer"], f"{name}.layer"),
                count=require_nonnegative_int(item["count"], f"{name}.count"),
            )
        )
    return tuple(result)
