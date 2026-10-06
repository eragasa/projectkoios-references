from __future__ import annotations

import projectkoios.references as references_api
from projectkoios.references.ingestion.evidence.artifact import (
    ReferenceEvidenceArtifact,
)
from projectkoios.references.ingestion.evidence.audit import (
    ReferenceEvidenceAudit,
)
from projectkoios.references.ingestion.evidence.extraction import (
    ReferenceEvidenceExtraction,
)
from projectkoios.references.ingestion.evidence.input import (
    ReferenceEvidenceInput,
)
from projectkoios.references.ingestion.evidence.layer.count import (
    ReferenceEvidenceLayerCount,
)
from projectkoios.references.ingestion.evidence.record.aggregate import (
    ReferenceEvidenceRecord,
)
from projectkoios.references.ingestion.evidence.source import (
    ReferenceEvidenceSource,
)
from projectkoios.references.ingestion.evidence.transcript import (
    ReferenceEvidenceTranscript,
)


def test__ingestion_evidence__records_are_slotted() -> None:
    for record_type in (
        ReferenceEvidenceArtifact,
        ReferenceEvidenceAudit,
        ReferenceEvidenceExtraction,
        ReferenceEvidenceInput,
        ReferenceEvidenceLayerCount,
        ReferenceEvidenceRecord,
        ReferenceEvidenceSource,
        ReferenceEvidenceTranscript,
    ):
        assert "__slots__" in vars(record_type)
        assert "__dict__" not in vars(record_type)


def test__ingestion_evidence__removed_facades_are_not_public_api() -> None:
    for name in (
        "IngestionEvidenceError",
        "IngestionEvidenceLimitError",
        "IngestionEvidenceParseError",
        "IngestionEvidenceVerificationError",
        "ReferenceEvidenceInput",
        "ReferenceEvidenceRecord",
        "load_ingestion_reference_evidence",
        "parse_reference_evidence",
        "verify_reference_evidence_source",
    ):
        assert not hasattr(references_api, name)
