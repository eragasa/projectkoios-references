from __future__ import annotations

from dataclasses import dataclass

from .artifact import ReferenceEvidenceArtifact
from .layer.count import ReferenceEvidenceLayerCount


@dataclass(frozen=True, slots=True)
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
