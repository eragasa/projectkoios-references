from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.acquisition import AcquisitionProjection
from projectkoios.references.assets import AssetDiscoveryPlan
from projectkoios.references.citation_closure import (
    CitationClosure,
)
from projectkoios.references.coverage import (
    CoverageAccessState,
    CoverageObservation,
    ReferenceCoverage,
)
from projectkoios.references.io_limits import (
    ReferenceIOLimits,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    PlaceholderObservation,
)
from projectkoios.references.reconciliation_package import (
    ContentEvidence,
    canonical_json_bytes,
)
from projectkoios.references.review import ReviewProjection
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
    StateKnowledge,
    StateResolution,
)

from .errors import CollectionReconciliationError
from .loading import CollectionRowEvidence, ManagedPdf


@final
@dataclass(frozen=True, init=False)
class ProcessingEvidence(DataObjectModel):
    ingestion_status: str
    transcript_status: str
    evidence_record_id: str | None
    contract_status: str
    derivation_audit_status: str
    derivation_audit_scope: str
    independently_revalidated: bool

    def __init__(self) -> None:
        raise TypeError(
            "ProcessingEvidence requires a named evidence constructor"
        )

    @classmethod
    def from_reference_evidence(
        cls,
        *,
        evidence_record_id: str,
        contract_status: str,
        derivation_audit_status: str,
        derivation_audit_scope: str,
        independently_revalidated: bool,
    ) -> ProcessingEvidence:
        if cls is not ProcessingEvidence:
            raise TypeError("ProcessingEvidence does not support subtypes")
        value = object.__new__(cls)
        for field_name, field_value in (
            ("ingestion_status", "completed-source-bound-reference-evidence"),
            (
                "transcript_status",
                "automated-unreviewed-with-recorded-passing-audit",
            ),
            ("evidence_record_id", evidence_record_id),
            ("contract_status", contract_status),
            ("derivation_audit_status", derivation_audit_status),
            ("derivation_audit_scope", derivation_audit_scope),
            ("independently_revalidated", independently_revalidated),
        ):
            object.__setattr__(value, field_name, field_value)
        value.__post_init__()
        return value

    @classmethod
    def not_supplied(cls) -> ProcessingEvidence:
        if cls is not ProcessingEvidence:
            raise TypeError("ProcessingEvidence does not support subtypes")
        value = object.__new__(cls)
        for field_name, field_value in (
            ("ingestion_status", "reference-evidence-not-supplied"),
            ("transcript_status", "reference-evidence-not-supplied"),
            ("evidence_record_id", None),
            ("contract_status", "not-supplied"),
            ("derivation_audit_status", "not-supplied"),
            ("derivation_audit_scope", "not-supplied"),
            ("independently_revalidated", False),
        ):
            object.__setattr__(value, field_name, field_value)
        value.__post_init__()
        return value

    def __post_init__(self) -> None:
        if self.evidence_record_id is None:
            if (
                self.ingestion_status,
                self.transcript_status,
                self.contract_status,
                self.derivation_audit_status,
                self.derivation_audit_scope,
                self.independently_revalidated,
            ) != (
                "reference-evidence-not-supplied",
                "reference-evidence-not-supplied",
                "not-supplied",
                "not-supplied",
                "not-supplied",
                False,
            ):
                raise ValueError(
                    "processing evidence without a record must be "
                    "explicitly not supplied"
                )
            return
        if (
            re.fullmatch(
                r"reference-evidence-record:sha256:[0-9a-f]{64}",
                self.evidence_record_id,
            )
            is None
        ):
            raise ValueError("processing evidence record identity is invalid")
        expected = (
            "completed-source-bound-reference-evidence",
            "automated-unreviewed-with-recorded-passing-audit",
            "proposed",
            "recorded-passing",
            "recorded_producer_derivation_audit",
            False,
        )
        actual = (
            self.ingestion_status,
            self.transcript_status,
            self.contract_status,
            self.derivation_audit_status,
            self.derivation_audit_scope,
            self.independently_revalidated,
        )
        if actual != expected:
            raise ValueError(
                "processing evidence status contradicts the supported "
                "producer record"
            )


def _bound_input_evidence(
    *,
    bibliography_bytes: bytes,
    collection_rows: Mapping[str, CollectionRowEvidence],
    managed_pdfs: Sequence[ManagedPdf],
    citation_closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None,
    coverage_observation_bytes: bytes | None,
    processing_evidence: Mapping[str, ProcessingEvidence] | None,
    acquisition_evidence: Mapping[str, AcquisitionProjection] | None,
    review_projection: ReviewProjection | None,
    catalog_assets: Mapping[str, tuple[SourceAssetRecord, ...]] | None,
    asset_plan: AssetDiscoveryPlan | None,
    limits: ReferenceIOLimits,
) -> tuple[ContentEvidence, ...]:
    evidence = [
        ContentEvidence.from_bytes(
            role="bibliography",
            filename="inputs/bibliography.bib",
            content=bibliography_bytes,
        ),
        ContentEvidence.from_bytes(
            role="effective-io-limits",
            filename="inputs/effective-io-limits.json",
            content=canonical_json_bytes(
                {
                    "schema_version": 1,
                    "coverage_status": "complete",
                    "effective_limits": limits.to_dict(),
                    "effective_limits_id": limits.evidence_id,
                }
            ),
        ),
    ]
    evidence.extend(_retained_input_evidence(collection_rows))
    if not _retained_input_evidence(collection_rows):
        evidence.append(
            ContentEvidence.from_bytes(
                role="collection-rows-normalized",
                filename="inputs/collection-rows.normalized.json",
                content=canonical_json_bytes(dict(collection_rows)),
            )
        )
    retained_assets = _retained_input_evidence(managed_pdfs)
    evidence.extend(retained_assets)
    if not retained_assets:
        evidence.extend(
            ContentEvidence(
                role="managed-asset",
                filename=f"inputs/managed-assets/{item.filename}",
                byte_size=item.byte_size,
                sha256=item.sha256,
            )
            for item in managed_pdfs
        )
    if citation_closure is not None:
        evidence.extend(citation_closure.source_file_evidence)
        evidence.append(
            ContentEvidence.from_bytes(
                role="citation-closure",
                filename="inputs/citation-closure.json",
                content=citation_closure.to_json().encode("utf-8"),
            )
        )
    if coverage_observation is not None:
        content = (
            coverage_observation_bytes
            if coverage_observation_bytes is not None
            else coverage_observation.to_json().encode("utf-8")
        )
        evidence.append(
            ContentEvidence.from_bytes(
                role="coverage-observation",
                filename="inputs/coverage-observation.json",
                content=content,
            )
        )
    if processing_evidence is not None:
        retained_processing = _retained_input_evidence(processing_evidence)
        evidence.extend(retained_processing)
        if not retained_processing:
            evidence.append(
                ContentEvidence.from_bytes(
                    role="processing-observation",
                    filename="inputs/processing-observation.json",
                    content=canonical_json_bytes(dict(processing_evidence)),
                )
            )
    if acquisition_evidence is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="acquisition-projection",
                filename="inputs/acquisition-projections.json",
                content=canonical_json_bytes(
                    {
                        key: asdict(value)
                        for key, value in sorted(acquisition_evidence.items())
                    }
                ),
            )
        )
    if review_projection is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="review-projection",
                filename="inputs/review-projection.json",
                content=review_projection.to_json().encode("utf-8"),
            )
        )
    if catalog_assets is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="catalog-asset-observations",
                filename="inputs/catalog-assets.json",
                content=canonical_json_bytes(dict(catalog_assets)),
            )
        )
    if asset_plan is not None:
        evidence.append(
            ContentEvidence.from_bytes(
                role="asset-discovery-plan",
                filename="inputs/asset-discovery-plan.json",
                content=asset_plan.to_json().encode("utf-8"),
            )
        )
    normalized = canonical_json_bytes(
        {
            "collection_rows": dict(collection_rows),
            "collection_rows_root_preflights": getattr(
                collection_rows, "root_preflights", ()
            ),
            "managed_pdfs": tuple(managed_pdfs),
            "managed_root_preflight": getattr(
                managed_pdfs, "root_preflight", None
            ),
            "managed_file_observations": getattr(
                managed_pdfs, "file_observations", ()
            ),
            "coverage_observation": coverage_observation,
            "processing_evidence": (
                None
                if processing_evidence is None
                else dict(processing_evidence)
            ),
            "processing_evidence_root_preflights": getattr(
                processing_evidence, "root_preflights", ()
            ),
            "acquisition_evidence": (
                None
                if acquisition_evidence is None
                else {
                    key: asdict(value)
                    for key, value in sorted(acquisition_evidence.items())
                }
            ),
            "review_projection_id": (
                None
                if review_projection is None
                else review_projection.projection_id
            ),
            "catalog_assets": (
                None if catalog_assets is None else dict(catalog_assets)
            ),
            "asset_plan": asset_plan,
        }
    )
    evidence.append(
        ContentEvidence.from_bytes(
            role="normalized-reconciliation-input",
            filename="inputs/reconciliation-input.normalized.json",
            content=normalized,
        )
    )
    ordered = tuple(
        sorted(
            evidence,
            key=lambda value: (
                value.role,
                value.filename,
                value.byte_size,
                value.sha256,
            ),
        )
    )
    filenames = tuple(item.filename for item in ordered)
    if len(filenames) != len(set(filenames)):
        raise CollectionReconciliationError(
            "bound input evidence contains duplicate filenames"
        )
    return ordered


def _retained_input_evidence(value: object) -> tuple[ContentEvidence, ...]:
    retained = getattr(value, "input_evidence", ())
    if not isinstance(retained, tuple) or any(
        not isinstance(item, ContentEvidence) for item in retained
    ):
        raise CollectionReconciliationError(
            "retained input evidence has an invalid representation"
        )
    return retained


def _coverage_evidence(
    evidence: ReferenceCoverage | None,
) -> tuple[str, ...]:
    if evidence is None:
        return ()
    values = set(evidence.evidence)
    values.update(
        f"candidate-content:sha256:{candidate.sha256}"
        for candidate in evidence.candidates
    )
    return tuple(sorted(values))


def _preflight_evidence(
    observation: PlaceholderObservation | None,
) -> tuple[str, ...]:
    if observation is None:
        return ()
    return (
        f"root-storage-class:{observation.storage_class.value}",
        f"placeholder-probe:{observation.probe_id}",
        f"path-preflight:{observation.status.value}",
    )


def _projected_status(
    projection: ReferenceStateProjection,
    field: str,
) -> str:
    projected = projection.field(field)
    if projected.resolution is StateResolution.DISCREPANCY:
        return StateResolution.DISCREPANCY.value
    if not projected.values:
        return StateKnowledge.NOT_OBSERVED.value
    value = projected.values[0]
    if value.knowledge is not StateKnowledge.OBSERVED:
        return value.knowledge.value
    parsed = value.value()
    if not isinstance(parsed, str):
        raise CollectionReconciliationError(
            f"projected {field} status is not text"
        )
    return parsed


def _access_status(
    *,
    matched_pdf: ManagedPdf | None,
    evidence: ReferenceCoverage | None,
    preflight: PlaceholderObservation | None = None,
) -> str:
    if matched_pdf is not None:
        return "managed-local-access"
    if preflight is not None:
        return preflight.status.value
    if evidence is None:
        return "not-assessed"
    if evidence.access_state is not CoverageAccessState.NONE:
        return evidence.access_state.value
    if evidence.candidates:
        return "candidate-access-unverified"
    return "searched-no-access-evidence"
