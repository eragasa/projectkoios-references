from __future__ import annotations

from dataclasses import dataclass

from .artifact import ReferenceEvidenceArtifact


@dataclass(frozen=True, slots=True)
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
