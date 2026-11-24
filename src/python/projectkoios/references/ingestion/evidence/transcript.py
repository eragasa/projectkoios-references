from __future__ import annotations

from dataclasses import dataclass

from .artifact import ReferenceEvidenceArtifact


@dataclass(frozen=True, slots=True)
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
