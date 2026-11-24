from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import final

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.acquisition import AcquisitionManifest
from projectkoios.references.assets import AssetDiscoveryPlan
from projectkoios.references.biblatex import (
    biblatex_parser_identity,
    load_bibliography,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.citation_closure import (
    CitationScanMode,
    build_citation_closure,
)
from projectkoios.references.coverage import CoverageObservation
from projectkoios.references.ingestion_evidence import (
    ReferenceEvidenceInput,
    load_ingestion_reference_evidence,
)
from projectkoios.references.io_limits import (
    ACQUISITION_IO_LIMITS,
    ASSET_DISCOVERY_IO_LIMITS,
    RECONCILIATION_IO_LIMITS,
    REVIEW_IO_LIMITS,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    RootStorageClass,
    read_path_bytes,
    read_path_text,
)
from projectkoios.references.review import ReviewProjection

from ._contract import _required_limit
from .loading import (
    CollectionRowsLoader,
    CollectionRowsLoadRequest,
    ManagedPdfScanner,
    ManagedPdfScanRequest,
)
from .publication import (
    ReconciliationPublicationRequest,
    ReconciliationPublicationResult,
    ReconciliationPublisher,
)
from .reconciliation import (
    CollectionReconciler,
    CollectionReconciliationRequest,
    CollectionReconciliationResult,
)

COLLECTION_RECONCILIATION_OPERATION_ACTION_ID = (
    "projectkoios.references.collections.reconciliation.operation@1"
)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionReconciliationOperationRequest(DataObjectActionRequest):
    """Bind explicit runtime capabilities to one complete owner operation."""

    bibliography: Path
    bibliography_storage_class: RootStorageClass
    corpus: Path
    corpus_storage_class: RootStorageClass
    pdfs: Path
    pdf_storage_class: RootStorageClass
    output_directory: Path
    output_storage_class: RootStorageClass
    collection_id: str
    source_revision: str
    source_discovery: Path | None = None
    source_discovery_storage_class: RootStorageClass | None = None
    coverage_observation: Path | None = None
    coverage_observation_storage_class: RootStorageClass | None = None
    acquisition_manifest: Path | None = None
    acquisition_manifest_storage_class: RootStorageClass | None = None
    review_projection: Path | None = None
    review_projection_storage_class: RootStorageClass | None = None
    catalog: Path | None = None
    catalog_storage_class: RootStorageClass | None = None
    asset_plan: Path | None = None
    asset_plan_storage_class: RootStorageClass | None = None
    manuscript_root: Path | None = None
    manuscript_storage_class: RootStorageClass | None = None
    manuscript_mode: CitationScanMode | None = None
    manuscript_entrypoint: str | None = None
    reference_evidence: tuple[ReferenceEvidenceInput, ...] = ()

    def __post_init__(self) -> None:
        for path_value, label in (
            (self.bibliography, "bibliography"),
            (self.corpus, "corpus"),
            (self.pdfs, "pdfs"),
            (self.output_directory, "output_directory"),
        ):
            if not isinstance(path_value, Path):
                raise TypeError(f"{label} must be a Path")
        for storage_value, label in (
            (self.bibliography_storage_class, "bibliography"),
            (self.corpus_storage_class, "corpus"),
            (self.pdf_storage_class, "pdf"),
            (self.output_storage_class, "output"),
        ):
            if not isinstance(storage_value, RootStorageClass):
                raise TypeError(f"{label} storage class must be explicit")
        if not isinstance(self.collection_id, str) or not self.collection_id:
            raise ValueError("collection_id must be non-empty")
        if (
            not isinstance(self.source_revision, str)
            or not self.source_revision
        ):
            raise ValueError("source_revision must be non-empty")
        for path, storage_class, label in (
            (
                self.source_discovery,
                self.source_discovery_storage_class,
                "source_discovery",
            ),
            (
                self.coverage_observation,
                self.coverage_observation_storage_class,
                "coverage_observation",
            ),
            (
                self.acquisition_manifest,
                self.acquisition_manifest_storage_class,
                "acquisition_manifest",
            ),
            (
                self.review_projection,
                self.review_projection_storage_class,
                "review_projection",
            ),
            (self.catalog, self.catalog_storage_class, "catalog"),
            (self.asset_plan, self.asset_plan_storage_class, "asset_plan"),
        ):
            if (path is None) != (storage_class is None):
                raise ValueError(
                    f"{label} path and storage class must be supplied together"
                )
            if path is not None and not isinstance(path, Path):
                raise TypeError(f"{label} must be a Path")
            if storage_class is not None and not isinstance(
                storage_class, RootStorageClass
            ):
                raise TypeError(f"{label} storage class must be explicit")
        manuscript_values = (
            self.manuscript_root,
            self.manuscript_storage_class,
            self.manuscript_mode,
        )
        if any(value is not None for value in manuscript_values) and any(
            value is None for value in manuscript_values
        ):
            raise ValueError(
                "manuscript root, storage class, and mode must be supplied "
                "together"
            )
        if self.manuscript_root is not None and not isinstance(
            self.manuscript_root, Path
        ):
            raise TypeError("manuscript_root must be a Path")
        if self.manuscript_storage_class is not None and not isinstance(
            self.manuscript_storage_class, RootStorageClass
        ):
            raise TypeError("manuscript storage class must be explicit")
        if self.manuscript_mode is not None and not isinstance(
            self.manuscript_mode, CitationScanMode
        ):
            raise TypeError("manuscript_mode must be a CitationScanMode")
        if self.manuscript_mode is CitationScanMode.BUILD_GRAPH:
            if not self.manuscript_entrypoint:
                raise ValueError(
                    "build-graph manuscript mode requires an entrypoint"
                )
        elif self.manuscript_entrypoint is not None:
            raise ValueError(
                "manuscript entrypoint is permitted only in build-graph mode"
            )
        if not isinstance(self.reference_evidence, tuple) or any(
            type(item) is not ReferenceEvidenceInput
            for item in self.reference_evidence
        ):
            raise TypeError(
                "reference_evidence must be a ReferenceEvidenceInput tuple"
            )
        evidence_keys = tuple(item.citekey for item in self.reference_evidence)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("reference_evidence citekeys must be unique")
        object.__setattr__(
            self,
            "reference_evidence",
            tuple(
                sorted(
                    self.reference_evidence,
                    key=lambda item: item.citekey,
                )
            ),
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionReconciliationOperationResult(DataObjectActionResult):
    """Bind the complete reconciliation and publication lifecycle results."""

    request: CollectionReconciliationOperationRequest
    reconciliation: CollectionReconciliationResult
    publication: ReconciliationPublicationResult

    def __post_init__(self) -> None:
        if type(self.request) is not CollectionReconciliationOperationRequest:
            raise TypeError(
                "request must be a CollectionReconciliationOperationRequest"
            )
        if type(self.reconciliation) is not CollectionReconciliationResult:
            raise TypeError(
                "reconciliation must be a CollectionReconciliationResult"
            )
        if type(self.publication) is not ReconciliationPublicationResult:
            raise TypeError(
                "publication must be a ReconciliationPublicationResult"
            )
        publication_request = self.publication.request
        if publication_request.outputs != self.reconciliation.outputs:
            raise ValueError(
                "publication outputs differ from reconciliation outputs"
            )
        if (
            publication_request.output_directory
            != self.request.output_directory
            or publication_request.output_storage_class
            is not self.request.output_storage_class
        ):
            raise ValueError(
                "publication destination differs from the operation request"
            )


@final
class CollectionReconciliationOperation(
    DataObjectActionizer[
        CollectionReconciliationOperationRequest,
        CollectionReconciliationOperationResult,
    ]
):
    """Execute one complete owner-defined reconciliation publication."""

    __slots__ = ()

    action_id = COLLECTION_RECONCILIATION_OPERATION_ACTION_ID

    def action(
        self, *, request: CollectionReconciliationOperationRequest
    ) -> CollectionReconciliationOperationResult:
        if type(request) is not CollectionReconciliationOperationRequest:
            raise TypeError(
                "request must be a CollectionReconciliationOperationRequest"
            )
        imported = load_bibliography(
            request.bibliography,
            source_id=request.collection_id,
            storage_class=request.bibliography_storage_class,
            source_revision=request.source_revision,
        )
        bibliography_bytes = imported.bibliography_bytes
        citation_closure = None
        if request.manuscript_root is not None:
            manuscript_storage_class = request.manuscript_storage_class
            manuscript_mode = request.manuscript_mode
            if manuscript_storage_class is None or manuscript_mode is None:
                raise ValueError("manuscript capabilities are incomplete")
            citation_closure = build_citation_closure(
                request.manuscript_root,
                storage_class=manuscript_storage_class,
                mode=manuscript_mode,
                entrypoint=request.manuscript_entrypoint,
                bibliography_keys=tuple(
                    sorted(
                        record.proposed_citekey
                        for record in imported.candidates
                    )
                ),
                source_revision=request.source_revision,
            )
        managed_pdfs = (
            ManagedPdfScanner()
            .action(
                request=ManagedPdfScanRequest(
                    directory=request.pdfs,
                    storage_class=request.pdf_storage_class,
                    source_discovery=request.source_discovery,
                    source_discovery_storage_class=(
                        request.source_discovery_storage_class
                        if request.source_discovery is not None
                        else None
                    ),
                )
            )
            .scan
        )
        processing_evidence = (
            load_ingestion_reference_evidence(
                request.reference_evidence,
                managed_pdfs=managed_pdfs,
            )
            if request.reference_evidence
            else None
        )
        coverage_observation_bytes = (
            read_path_bytes(
                request.coverage_observation,
                label="coverage observation",
                root_alias="coverage-observation",
                storage_class=request.coverage_observation_storage_class,
                max_bytes=_required_limit(
                    RECONCILIATION_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
            if request.coverage_observation is not None
            and request.coverage_observation_storage_class is not None
            else None
        )
        coverage_observation = (
            CoverageObservation.from_json(
                coverage_observation_bytes.decode("utf-8")
            )
            if coverage_observation_bytes is not None
            else None
        )
        acquisition_manifest = (
            AcquisitionManifest.from_json(
                read_path_text(
                    request.acquisition_manifest,
                    label="acquisition manifest",
                    root_alias="acquisition-manifest",
                    storage_class=(request.acquisition_manifest_storage_class),
                    max_bytes=_required_limit(
                        ACQUISITION_IO_LIMITS.max_json_bytes,
                        "max_json_bytes",
                    ),
                )
            )
            if request.acquisition_manifest is not None
            and request.acquisition_manifest_storage_class is not None
            else None
        )
        acquisition_evidence = (
            {
                item.proposed_citekey: item
                for item in acquisition_manifest.projections()
            }
            if acquisition_manifest is not None
            else None
        )
        review_projection = (
            ReviewProjection.from_json(
                read_path_text(
                    request.review_projection,
                    label="review projection",
                    root_alias="review-projection",
                    storage_class=request.review_projection_storage_class,
                    max_bytes=_required_limit(
                        REVIEW_IO_LIMITS.max_json_bytes,
                        "max_json_bytes",
                    ),
                )
            )
            if request.review_projection is not None
            and request.review_projection_storage_class is not None
            else None
        )
        catalog_assets = None
        if (
            request.catalog is not None
            and request.catalog_storage_class is not None
        ):
            grouped_assets: dict[str, list[SourceAssetRecord]] = {}
            for asset in ReferenceCatalog(
                request.catalog,
                storage_class=request.catalog_storage_class,
            ).read_source_assets(
                max_records=_required_limit(
                    RECONCILIATION_IO_LIMITS.max_candidates,
                    "max_candidates",
                )
            ):
                grouped_assets.setdefault(
                    asset.proposed_citekey,
                    [],
                ).append(asset)
            catalog_assets = {
                citekey: tuple(sorted(values, key=lambda item: item.sha256))
                for citekey, values in sorted(grouped_assets.items())
            }
        asset_plan = (
            AssetDiscoveryPlan.from_json(
                read_path_text(
                    request.asset_plan,
                    label="asset discovery plan",
                    root_alias="asset-plan-input",
                    storage_class=request.asset_plan_storage_class,
                    max_bytes=_required_limit(
                        ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                        "max_json_bytes",
                    ),
                )
            )
            if request.asset_plan is not None
            and request.asset_plan_storage_class is not None
            else None
        )
        collection_rows = (
            CollectionRowsLoader()
            .action(
                request=CollectionRowsLoadRequest(
                    path=request.corpus,
                    storage_class=request.corpus_storage_class,
                )
            )
            .rows
        )
        reconciliation = CollectionReconciler().action(
            request=CollectionReconciliationRequest(
                records=imported.candidates,
                bibliography_bytes=bibliography_bytes,
                collection_id=request.collection_id,
                source_revision=request.source_revision,
                collection_rows=collection_rows,
                managed_pdfs=managed_pdfs,
                citation_closure=citation_closure,
                coverage_observation=coverage_observation,
                coverage_observation_bytes=coverage_observation_bytes,
                processing_evidence=processing_evidence,
                acquisition_evidence=acquisition_evidence,
                review_projection=review_projection,
                catalog_assets=catalog_assets,
                asset_plan=asset_plan,
                bibliography_parser=biblatex_parser_identity(),
            )
        )
        publication = ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=reconciliation.outputs,
                output_directory=request.output_directory,
                output_storage_class=request.output_storage_class,
            )
        )
        return CollectionReconciliationOperationResult(
            request=request,
            reconciliation=reconciliation,
            publication=publication,
        )
