from __future__ import annotations

from collections.abc import Iterable, Sequence

from projectkoios.references.collections.reconciliation.evidence import (
    ProcessingEvidence,
)
from projectkoios.references.collections.reconciliation.loading import (
    EvidenceMapping,
    ManagedPdf,
)
from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)
from projectkoios.references.filesystem.path.read import read_path_bytes
from projectkoios.references.filesystem.root.preflight.action import (
    authorize_root_preflight,
)
from projectkoios.references.filesystem.root.preflight.evidence import (
    RootPreflightEvidence,
)
from projectkoios.references.reconciliation_package import (
    ContentEvidence,
    canonical_json_bytes,
)

from ..contract import (
    REFERENCE_EVIDENCE_ADAPTER_VERSION,
    REFERENCE_EVIDENCE_CONTRACT_STATUS,
    REFERENCE_EVIDENCE_MAX_BYTES,
    REFERENCE_EVIDENCE_MAX_INPUTS,
)
from ..error import (
    IngestionEvidenceLimitError,
    IngestionEvidenceVerificationError,
)
from ..input import ReferenceEvidenceInput
from ..media import SOURCE_MEDIA_TYPE
from ..parsing.action import parse_reference_evidence
from ..verification.action import verify_reference_evidence_source


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
        except FilesystemOperationError as error:
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
            source_media_type=SOURCE_MEDIA_TYPE,
        )
        record_ids.add(record.record_id)
        result[binding.citekey] = ProcessingEvidence.from_reference_evidence(
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


def _content_evidence_key(
    value: ContentEvidence,
) -> tuple[str, str, int, str]:
    return (value.role, value.filename, value.byte_size, value.sha256)
