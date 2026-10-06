from __future__ import annotations

from dataclasses import asdict, dataclass

from ..audit import ReferenceEvidenceAudit
from ..extraction import ReferenceEvidenceExtraction
from ..source import ReferenceEvidenceSource
from ..transcript import ReferenceEvidenceTranscript
from .serialization import canonical_reference_evidence_bytes


@dataclass(frozen=True, slots=True)
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
        return canonical_reference_evidence_bytes(asdict(self))
