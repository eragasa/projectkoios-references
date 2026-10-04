from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import final

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.acquisition import AcquisitionProjection
from projectkoios.references.assets import AssetDiscoveryPlan
from projectkoios.references.citation_closure import (
    CITATION_PARSER_VERSION,
    CitationClosure,
)
from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageObservation,
    CoverageState,
)
from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.io_limits import (
    RECONCILIATION_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    PathSafetyError,
    PlaceholderObservation,
    validate_citekey,
)
from projectkoios.references.reconciliation_package import (
    PACKAGE_MANIFEST_FILENAME,
    FrozenCounts,
    ReconciliationPackageError,
    ReconciliationPackageManifest,
    SoftwareIdentity,
    parse_package_files,
)
from projectkoios.references.review import ReviewProjection
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
    StateResolution,
    build_reference_state_projection,
)

from ._contract import (
    _COLLECTION_ROWS_PARSER_VERSION,
    _PROCESSOR_VERSION,
    _REFERENCE_EVIDENCE_CONSUMER_VERSION,
    _SCHEMA_VERSION,
    _SOURCE_DISCOVERY_PARSER_VERSION,
    _required_limit,
    _stable_id,
)
from .classification import (
    CitationStatus,
    CollectionReference,
    ExtraPdf,
    _classify_asset_plan_status,
    _classify_pdf_status,
    _counts,
    _coverage_claims,
    _full_text_expected,
    _pdf_expectation,
    _source_type,
)
from .errors import CollectionReconciliationError
from .evidence import (
    ProcessingEvidence,
    _bound_input_evidence,
    _coverage_evidence,
    _preflight_evidence,
    _projected_status,
)
from .loading import (
    CollectionRowEvidence,
    EvidenceMapping,
    ManagedPdf,
    ManagedPdfScan,
)
from .manifest import CollectionManifest, ReconciliationOutputs
from .rendering import _render_outputs


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionReconciliationRequest(DataObjectActionRequest):
    records: tuple[ReferenceCandidate, ...]
    bibliography_bytes: bytes
    collection_id: str
    source_revision: str
    collection_rows: Mapping[str, CollectionRowEvidence]
    managed_pdfs: Sequence[ManagedPdf]
    citation_closure: CitationClosure | None
    coverage_observation: CoverageObservation | None = None
    coverage_observation_bytes: bytes | None = None
    processing_evidence: Mapping[str, ProcessingEvidence] | None = None
    acquisition_evidence: Mapping[str, AcquisitionProjection] | None = None
    review_projection: ReviewProjection | None = None
    catalog_assets: Mapping[str, tuple[SourceAssetRecord, ...]] | None = None
    asset_plan: AssetDiscoveryPlan | None = None
    bibliography_parser: str = "caller-supplied-records"
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        rows = self.collection_rows
        object.__setattr__(
            self,
            "collection_rows",
            EvidenceMapping(
                entries=tuple(sorted(rows.items())),
                input_evidence=tuple(getattr(rows, "input_evidence", ())),
                root_preflights=tuple(getattr(rows, "root_preflights", ())),
            ),
        )
        managed = self.managed_pdfs
        if type(managed) is not ManagedPdfScan:
            object.__setattr__(self, "managed_pdfs", tuple(managed))
        processing = self.processing_evidence
        if processing is not None:
            object.__setattr__(
                self,
                "processing_evidence",
                EvidenceMapping(
                    entries=tuple(sorted(processing.items())),
                    input_evidence=tuple(
                        getattr(processing, "input_evidence", ())
                    ),
                    root_preflights=tuple(
                        getattr(processing, "root_preflights", ())
                    ),
                ),
            )
        acquisition = self.acquisition_evidence
        if acquisition is not None:
            object.__setattr__(
                self,
                "acquisition_evidence",
                EvidenceMapping(
                    entries=tuple(sorted(acquisition.items())),
                    input_evidence=(),
                ),
            )
        assets = self.catalog_assets
        if assets is not None:
            object.__setattr__(
                self,
                "catalog_assets",
                EvidenceMapping(
                    entries=tuple(
                        (key, tuple(values))
                        for key, values in sorted(assets.items())
                    ),
                    input_evidence=(),
                ),
            )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionReconciliationResult(DataObjectActionResult):
    request: CollectionReconciliationRequest
    outputs: ReconciliationOutputs


@final
class CollectionReconciler(
    DataObjectActionizer[
        CollectionReconciliationRequest, CollectionReconciliationResult
    ]
):
    def action(
        self, *, request: CollectionReconciliationRequest
    ) -> CollectionReconciliationResult:
        if type(request) is not CollectionReconciliationRequest:
            raise TypeError("request must be a CollectionReconciliationRequest")
        records = request.records
        bibliography_bytes = request.bibliography_bytes
        collection_id = request.collection_id
        source_revision = request.source_revision
        collection_rows = request.collection_rows
        managed_pdfs = request.managed_pdfs
        citation_closure = request.citation_closure
        coverage_observation = request.coverage_observation
        coverage_observation_bytes = request.coverage_observation_bytes
        processing_evidence = request.processing_evidence
        acquisition_evidence = request.acquisition_evidence
        review_projection = request.review_projection
        catalog_assets = request.catalog_assets
        asset_plan = request.asset_plan
        bibliography_parser = request.bibliography_parser
        limits = request.limits
        if type(records) is not tuple or any(
            type(item) is not ReferenceCandidate for item in records
        ):
            raise CollectionReconciliationError(
                "bibliography records must be an exact immutable tuple"
            )
        if any(
            type(item) is not CollectionRowEvidence
            for item in collection_rows.values()
        ):
            raise CollectionReconciliationError(
                "collection rows must contain exact typed evidence"
            )
        if any(type(item) is not ManagedPdf for item in managed_pdfs):
            raise CollectionReconciliationError(
                "managed PDFs must contain exact typed evidence"
            )
        if (
            citation_closure is not None
            and type(citation_closure) is not CitationClosure
        ):
            raise CollectionReconciliationError(
                "citation closure must be a complete typed closure"
            )
        if (
            coverage_observation is not None
            and type(coverage_observation) is not CoverageObservation
        ):
            raise CollectionReconciliationError(
                "coverage observation must be exact typed evidence"
            )
        if type(limits) is not ReferenceIOLimits:
            raise CollectionReconciliationError(
                "I/O limits must be exact typed evidence"
            )
        if getattr(managed_pdfs, "file_observations", ()):
            raise CollectionReconciliationError(
                "complete reconciliation cannot consume skipped managed-PDF "
                "observations"
            )
        if not collection_id or not source_revision:
            raise CollectionReconciliationError(
                "collection and asserted source revision must be non-empty"
            )
        if not bibliography_parser:
            raise CollectionReconciliationError(
                "bibliography parser identity must be non-empty"
            )
        if coverage_observation_bytes is not None:
            if coverage_observation is None:
                raise CollectionReconciliationError(
                    "coverage bytes were supplied without an observation"
                )
            try:
                parsed_coverage = CoverageObservation.from_json(
                    coverage_observation_bytes.decode("utf-8")
                )
            except (UnicodeDecodeError, ValueError) as error:
                raise CollectionReconciliationError(
                    "coverage observation bytes are invalid"
                ) from error
            if parsed_coverage != coverage_observation:
                raise CollectionReconciliationError(
                    "coverage observation bytes differ from parsed evidence"
                )
        max_records = _required_limit(limits.max_candidates, "max_candidates")
        if not records:
            raise CollectionReconciliationError("bibliography has no records")
        if len(records) > max_records:
            raise ReferenceIOLimitError(
                resource="bibliography records",
                limit_name="max_candidates",
                limit=max_records,
                observed=len(records),
                limits=limits,
            )
        max_files = _required_limit(limits.max_files, "max_files")
        if len(managed_pdfs) > max_files:
            raise ReferenceIOLimitError(
                resource="managed PDF observations",
                limit_name="max_files",
                limit=max_files,
                observed=len(managed_pdfs),
                limits=limits,
            )
        max_rows = _required_limit(limits.max_rows, "max_rows")
        if len(collection_rows) > max_rows:
            raise ReferenceIOLimitError(
                resource="collection row observations",
                limit_name="max_rows",
                limit=max_rows,
                observed=len(collection_rows),
                limits=limits,
            )
        if (
            processing_evidence is not None
            and len(processing_evidence) > max_records
        ):
            raise ReferenceIOLimitError(
                resource="processing evidence observations",
                limit_name="max_candidates",
                limit=max_records,
                observed=len(processing_evidence),
                limits=limits,
            )
        if (
            acquisition_evidence is not None
            and len(acquisition_evidence) > max_records
        ):
            raise ReferenceIOLimitError(
                resource="acquisition evidence observations",
                limit_name="max_candidates",
                limit=max_records,
                observed=len(acquisition_evidence),
                limits=limits,
            )
        if (
            asset_plan is not None
            and type(asset_plan) is not AssetDiscoveryPlan
        ):
            raise CollectionReconciliationError(
                "asset_plan must be a typed AssetDiscoveryPlan"
            )
        catalog_asset_count = sum(
            len(values) for values in (catalog_assets or {}).values()
        )
        if catalog_asset_count > max_records:
            raise ReferenceIOLimitError(
                resource="catalog asset observations",
                limit_name="max_candidates",
                limit=max_records,
                observed=catalog_asset_count,
                limits=limits,
            )
        if asset_plan is not None and len(asset_plan.candidates) > max_records:
            raise ReferenceIOLimitError(
                resource="asset plan candidates",
                limit_name="max_candidates",
                limit=max_records,
                observed=len(asset_plan.candidates),
                limits=limits,
            )
        max_bibliography_bytes = _required_limit(
            limits.max_bibliography_bytes, "max_bibliography_bytes"
        )
        if len(bibliography_bytes) > max_bibliography_bytes:
            raise ReferenceIOLimitError(
                resource="bibliography bytes",
                limit_name="max_bibliography_bytes",
                limit=max_bibliography_bytes,
                observed=len(bibliography_bytes),
                limits=limits,
            )
        processing_supplied = processing_evidence is not None
        processing_by_citekey = processing_evidence or {}
        acquisition_supplied = acquisition_evidence is not None
        acquisition_by_citekey = acquisition_evidence or {}
        catalog_assets_by_citekey = catalog_assets or {}
        if (
            review_projection is not None
            and type(review_projection) is not ReviewProjection
        ):
            raise CollectionReconciliationError(
                "review_projection must be a replayed ReviewProjection"
            )
        coverage_by_citekey = (
            coverage_observation.by_citekey()
            if coverage_observation is not None
            else {}
        )
        ordered_records = tuple(
            sorted(records, key=lambda item: item.proposed_citekey)
        )
        try:
            citekeys = tuple(
                validate_citekey(record.proposed_citekey)
                for record in ordered_records
            )
            for managed_pdf in managed_pdfs:
                validate_citekey(
                    managed_pdf.citekey, field="managed PDF citekey"
                )
            for citekey in processing_by_citekey:
                validate_citekey(citekey, field="processing-evidence citekey")
            for citekey in acquisition_by_citekey:
                validate_citekey(citekey, field="acquisition-evidence citekey")
            for citekey in catalog_assets_by_citekey:
                validate_citekey(citekey, field="catalog-asset citekey")
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        if len(citekeys) != len(set(citekeys)):
            raise CollectionReconciliationError(
                "bibliography contains duplicate citekeys"
            )
        if coverage_observation is not None:
            if coverage_observation.asserted_source_revision != source_revision:
                raise CollectionReconciliationError(
                    "coverage observation source assertion differs"
                )
            extra_coverage = sorted(set(coverage_by_citekey) - set(citekeys))
            if extra_coverage:
                raise CollectionReconciliationError(
                    "coverage observation has references outside the "
                    f"bibliography: {extra_coverage}"
                )
            if coverage_observation.state is CoverageState.COMPLETE and set(
                coverage_by_citekey
            ) != set(citekeys):
                missing_coverage = sorted(
                    set(citekeys) - set(coverage_by_citekey)
                )
                raise CollectionReconciliationError(
                    "complete coverage omits bibliography references: "
                    f"{missing_coverage}"
                )
        if set(collection_rows) != set(citekeys):
            missing = sorted(set(citekeys) - set(collection_rows))
            extra = sorted(set(collection_rows) - set(citekeys))
            raise CollectionReconciliationError(
                f"collection row coverage differs: missing={missing}, "
                f"extra={extra}"
            )
        if citation_closure is not None:
            if (
                citation_closure.asserted_source_revision != source_revision
                or set(citation_closure.bibliography_keys) != set(citekeys)
            ):
                raise CollectionReconciliationError(
                    "citation closure does not match bibliography source"
                )
        by_citekey = {item.citekey: item for item in managed_pdfs}
        preflight_by_citekey: dict[str, PlaceholderObservation] = {}
        for item in getattr(managed_pdfs, "file_observations", ()):
            if item.relative_path is None:
                raise CollectionReconciliationError(
                    "managed-root file observation has no relative path"
                )
            citekey = validate_citekey(Path(item.relative_path).stem)
            if citekey in preflight_by_citekey or citekey in by_citekey:
                raise CollectionReconciliationError(
                    "managed PDF preflight has duplicate citekey stems"
                )
            preflight_by_citekey[citekey] = item
        if len(by_citekey) != len(managed_pdfs):
            raise CollectionReconciliationError(
                "managed PDF directory has duplicate citekey stems"
            )
        unmatched_processing = sorted(
            set(processing_by_citekey) - set(by_citekey)
        )
        if unmatched_processing:
            raise CollectionReconciliationError(
                "processing evidence has no matching managed PDF: "
                f"{unmatched_processing}"
            )
        if any(
            type(item) is not ProcessingEvidence
            or item.evidence_record_id is None
            for item in processing_by_citekey.values()
        ):
            raise CollectionReconciliationError(
                "supplied processing evidence is not source-bound producer "
                "evidence"
            )
        unmatched_acquisition = sorted(
            set(acquisition_by_citekey) - set(citekeys)
        )
        if unmatched_acquisition:
            raise CollectionReconciliationError(
                "acquisition evidence has no matching candidate: "
                f"{unmatched_acquisition}"
            )
        if any(
            type(item) is not AcquisitionProjection
            for item in acquisition_by_citekey.values()
        ):
            raise CollectionReconciliationError(
                "supplied acquisition evidence is not a typed projection"
            )
        unmatched_catalog_assets = sorted(
            set(catalog_assets_by_citekey) - set(citekeys)
        )
        if unmatched_catalog_assets:
            raise CollectionReconciliationError(
                "catalog assets have no matching candidate: "
                f"{unmatched_catalog_assets}"
            )
        if any(
            type(values) is not tuple
            or any(type(item) is not SourceAssetRecord for item in values)
            for values in catalog_assets_by_citekey.values()
        ):
            raise CollectionReconciliationError(
                "catalog assets must be typed immutable tuples"
            )
        candidate_ids = {item.candidate_id for item in ordered_records}
        if asset_plan is not None:
            unmatched_plan = sorted(
                {
                    item.candidate_id
                    for item in asset_plan.candidates
                    if item.candidate_id not in candidate_ids
                }
            )
            if unmatched_plan:
                raise CollectionReconciliationError(
                    f"asset plan has no matching candidates: {unmatched_plan}"
                )
        by_digest: dict[str, list[str]] = defaultdict(list)
        for managed_pdf in managed_pdfs:
            by_digest[managed_pdf.sha256].append(managed_pdf.citekey)
        cited = (
            set(citation_closure.cited_and_defined)
            if citation_closure is not None
            else set()
        )
        references: list[CollectionReference] = []
        state_projections: list[ReferenceStateProjection] = []
        for record in ordered_records:
            evidence = collection_rows[record.proposed_citekey]
            matched_pdf = by_citekey.get(record.proposed_citekey)
            expectation = _pdf_expectation(record)
            processing = processing_by_citekey.get(
                record.proposed_citekey, ProcessingEvidence.not_supplied()
            )
            acquisition = acquisition_by_citekey.get(record.proposed_citekey)
            coverage_item = coverage_by_citekey.get(record.proposed_citekey)
            preflight_item = preflight_by_citekey.get(record.proposed_citekey)
            status, next_action = _classify_pdf_status(
                matched_pdf=matched_pdf,
                expectation=expectation,
                observation=coverage_observation,
                evidence=coverage_item,
                preflight=preflight_item,
            )
            plan_candidates = (
                asset_plan.connected_candidates((record.candidate_id,))
                if asset_plan is not None
                else ()
            )
            if (
                matched_pdf is None
                and asset_plan is not None
                and plan_candidates
            ):
                status, next_action = _classify_asset_plan_status(
                    candidate_id=record.candidate_id,
                    asset_plan=asset_plan,
                    fallback=(status, next_action),
                )
            duplicate_citekeys = (
                tuple(
                    sorted(
                        key
                        for key in by_digest[matched_pdf.sha256]
                        if key != record.proposed_citekey
                    )
                )
                if matched_pdf is not None
                else ()
            )
            citation_status = (
                CitationStatus.CLOSURE_UNAVAILABLE
                if citation_closure is None
                else CitationStatus.CITED_DEFINED
                if record.proposed_citekey in cited
                else CitationStatus.DEFINED_UNCITED
            )
            state_projection = build_reference_state_projection(
                candidate=record,
                collection_id=collection_id,
                collection_row=evidence,
                managed_asset=matched_pdf,
                acquisition=acquisition,
                processing=processing
                if processing.evidence_record_id is not None
                else None,
                review=review_projection,
                coverage=coverage_observation,
                catalog_assets=catalog_assets_by_citekey.get(
                    record.proposed_citekey, ()
                ),
                asset_plan=asset_plan,
                citation_status=citation_status.value
                if citation_closure is not None
                else None,
                citation_input_id=citation_closure.closure_id
                if citation_closure is not None
                else None,
            )
            state_projections.append(state_projection)
            discrepancy_fields = tuple(
                item.field
                for item in state_projection.fields
                if item.resolution is StateResolution.DISCREPANCY
            )
            references.append(
                CollectionReference(
                    proposed_citekey=record.proposed_citekey,
                    identity_status=record.lifecycle_status,
                    citekey_status=record.citekey_status,
                    entry_type=record.entry_type,
                    source_type=_source_type(record),
                    full_text_expected=_full_text_expected(expectation),
                    title=record.title,
                    year=record.year,
                    doi=record.doi,
                    source_bibliographies=evidence.source_bibliographies,
                    metadata_verification_status=evidence.bibliographic_status,
                    reading_status=evidence.reading_status,
                    reading_decision_status=_projected_status(
                        state_projection, "reading_decision"
                    ),
                    citation_status=citation_status,
                    pdf_expectation=expectation,
                    pdf_status=status,
                    managed_pdf=matched_pdf.filename
                    if matched_pdf is not None
                    else None,
                    sha256=matched_pdf.sha256
                    if matched_pdf is not None
                    else None,
                    byte_size=matched_pdf.byte_size
                    if matched_pdf is not None
                    else None,
                    discovery_evidence=matched_pdf.discovery_evidence
                    if matched_pdf is not None
                    else tuple(
                        sorted(item.observation_id for item in plan_candidates)
                    )
                    if plan_candidates
                    else _preflight_evidence(preflight_item)
                    if preflight_item is not None
                    else _coverage_evidence(coverage_item),
                    duplicate_citekeys=duplicate_citekeys,
                    acquisition_status=_projected_status(
                        state_projection, "acquisition_status"
                    ),
                    access_status=_projected_status(
                        state_projection, "access_status"
                    ),
                    rights_status=_projected_status(
                        state_projection, "rights_status"
                    ),
                    ingestion_status=processing.ingestion_status,
                    transcript_status=processing.transcript_status,
                    state_projection_id=state_projection.projection_id,
                    state_discrepancy_fields=discrepancy_fields,
                    next_lawful_action=next_action,
                )
            )
        seed = set(citekeys)
        extras = tuple(
            ExtraPdf(
                filename=pdf.filename,
                proposed_citekey=pdf.citekey,
                sha256=pdf.sha256,
                byte_size=pdf.byte_size,
                duplicate_citekeys=tuple(
                    sorted(
                        key
                        for key in by_digest[pdf.sha256]
                        if key != pdf.citekey
                    )
                ),
                access_status="managed-local-access",
                rights_status="not-assessed",
                ingestion_status=processing_by_citekey.get(
                    pdf.citekey, ProcessingEvidence.not_supplied()
                ).ingestion_status,
                transcript_status=processing_by_citekey.get(
                    pdf.citekey, ProcessingEvidence.not_supplied()
                ).transcript_status,
            )
            for pdf in managed_pdfs
            if pdf.citekey not in seed
        )
        counts = FrozenCounts(
            _counts(tuple(references), extras, citation_closure)
        )
        coverage = _coverage_claims(
            coverage_observation=coverage_observation,
            processing_supplied=processing_supplied,
            acquisition_supplied=acquisition_supplied,
            review_supplied=review_projection is not None,
            citation_closure_supplied=citation_closure is not None,
        )
        bibliography_sha256 = hashlib.sha256(bibliography_bytes).hexdigest()
        manifest_payload = {
            "schema_version": _SCHEMA_VERSION,
            "processor_version": _PROCESSOR_VERSION,
            "collection_id": collection_id,
            "asserted_source_revision": source_revision,
            "bibliography_sha256": bibliography_sha256,
            "coverage_observation_id": coverage_observation.coverage_id
            if coverage_observation is not None
            else None,
            "coverage_state": coverage_observation.state
            if coverage_observation is not None
            else None,
            "ambiguity_evaluation": coverage_observation.ambiguity_evaluation
            if coverage_observation is not None
            else AmbiguityEvaluation.NOT_EVALUATED,
            "coverage": list(coverage),
            "state_projections": [
                json.loads(item.to_json()) for item in state_projections
            ],
            "references": [asdict(record) for record in references],
            "extra_pdfs": [asdict(extra) for extra in extras],
            "counts": counts,
        }
        manifest = CollectionManifest(
            schema_version=_SCHEMA_VERSION,
            processor_version=_PROCESSOR_VERSION,
            collection_id=collection_id,
            asserted_source_revision=source_revision,
            bibliography_sha256=bibliography_sha256,
            coverage_observation_id=coverage_observation.coverage_id
            if coverage_observation is not None
            else None,
            coverage_state=coverage_observation.state
            if coverage_observation is not None
            else None,
            ambiguity_evaluation=coverage_observation.ambiguity_evaluation
            if coverage_observation is not None
            else AmbiguityEvaluation.NOT_EVALUATED,
            coverage=coverage,
            state_projections=tuple(state_projections),
            references=tuple(references),
            extra_pdfs=extras,
            counts=counts,
            manifest_id=_stable_id("collection-manifest", manifest_payload),
        )
        rendered = _render_outputs(
            manifest, citation_closure, coverage_observation
        )
        inputs = _bound_input_evidence(
            bibliography_bytes=bibliography_bytes,
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
            limits=limits,
        )
        package_manifest = ReconciliationPackageManifest.create(
            collection_id=collection_id,
            asserted_source_revision=source_revision,
            verified_source_tree=citation_closure.verified_source_tree
            if citation_closure is not None
            else None,
            components=(
                SoftwareIdentity(
                    name="collection-reconciliation", version=_PROCESSOR_VERSION
                ),
                SoftwareIdentity(
                    name="collection-rows-parser",
                    version=_COLLECTION_ROWS_PARSER_VERSION,
                ),
                SoftwareIdentity(
                    name="source-discovery-parser",
                    version=_SOURCE_DISCOVERY_PARSER_VERSION,
                ),
                SoftwareIdentity(
                    name="ingestion-reference-evidence-consumer",
                    version=_REFERENCE_EVIDENCE_CONSUMER_VERSION,
                ),
                SoftwareIdentity(
                    name="latex-citation-parser",
                    version=citation_closure.parser_configuration.parser_version
                    if citation_closure is not None
                    else CITATION_PARSER_VERSION,
                ),
                SoftwareIdentity(
                    name="bibliography-parser", version=bibliography_parser
                ),
                SoftwareIdentity(name="reference-io-limits", version="1"),
            ),
            inputs=inputs,
            output_files=rendered,
        )
        rendered[PACKAGE_MANIFEST_FILENAME] = package_manifest.to_json().encode(
            "utf-8"
        )
        files = tuple(sorted(rendered.items()))
        try:
            parse_package_files(dict(files))
        except ReconciliationPackageError as error:
            raise CollectionReconciliationError(str(error)) from error
        return CollectionReconciliationResult(
            request=request,
            outputs=ReconciliationOutputs(
                manifest=manifest,
                citation_closure=citation_closure,
                package_manifest=package_manifest,
                files=files,
            ),
        )
