from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict
from pathlib import Path

from projectkoios.references.acquisition import (
    AcquisitionManifest,
    create_acquisition_manifest,
    publish_acquisition_manifest,
    verify_acquisition_manifest,
)
from projectkoios.references.assets import (
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    AssetMaterializationResult,
    CanonicalAssetAuthorization,
    SearchRoot,
    materialize_asset_with_result,
    rollback_materialized_asset,
)
from projectkoios.references.biblatex import (
    biblatex_parser_identity,
    load_bibliography,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.collection_reconciliation import (
    build_citation_closure,
    load_collection_rows,
    publish_reconciliation,
    reconcile_collection,
    scan_managed_pdfs,
)
from projectkoios.references.coverage import CoverageObservation
from projectkoios.references.enrichment import CrossrefClient
from projectkoios.references.graph import load_candidate_graph
from projectkoios.references.identity import IdentityProjection
from projectkoios.references.ingestion_evidence import (
    ReferenceEvidenceInput,
    load_ingestion_reference_evidence,
)
from projectkoios.references.io_limits import (
    ACQUISITION_IO_LIMITS,
    ASSET_DISCOVERY_IO_LIMITS,
    RECONCILIATION_IO_LIMITS,
    REVIEW_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_csv_field_size,
    bounded_utf8_size,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    PathLimitError,
    RootStorageClass,
    read_path_bytes,
    read_path_text,
    write_path_bytes,
)
from projectkoios.references.review import ReviewProjection
from projectkoios.references.validation import validate_reference_objects


def _root(value: str) -> SearchRoot:
    storage, class_separator, remainder = value.partition(":")
    if not class_separator:
        raise argparse.ArgumentTypeError(
            "root storage class is required; use local:ALIAS=PATH or "
            "cloud-backed:ALIAS=PATH"
        )
    try:
        storage_class = RootStorageClass(storage)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "root storage class must be local or cloud-backed"
        ) from error
    alias, separator, raw_path = remainder.partition("=")
    if not separator or not alias or not raw_path:
        raise argparse.ArgumentTypeError(
            "root must be STORAGE:ALIAS=PATH; for example, "
            "local:papers=/path/to/staging"
        )
    return SearchRoot(alias, Path(raw_path).expanduser(), storage_class)


def _storage_class(value: str) -> RootStorageClass:
    try:
        return RootStorageClass(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "storage class must be local or cloud-backed"
        ) from error


def _reference_evidence(value: str) -> tuple[str, Path]:
    citekey, separator, raw_path = value.partition("=")
    if not separator or not citekey or not raw_path:
        raise argparse.ArgumentTypeError(
            "reference evidence must be CITEKEY=PATH"
        )
    try:
        return citekey, Path(raw_path).expanduser()
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _keyed_storage_class(value: str) -> tuple[str, RootStorageClass]:
    key, separator, raw_class = value.partition("=")
    if not separator or not key:
        raise argparse.ArgumentTypeError(
            "keyed storage class must be KEY=local or KEY=cloud-backed"
        )
    return key, _storage_class(raw_class)


def _paired_storage_class(
    path: Path | None,
    storage_class: RootStorageClass | None,
    *,
    label: str,
) -> RootStorageClass | None:
    if (path is None) != (storage_class is None):
        raise SystemExit(
            f"{label} path and --{label}-storage-class must be supplied "
            "together"
        )
    return storage_class


def _reject_duplicate_storage_options(arguments: list[str]) -> None:
    seen: set[str] = set()
    repeatable = {"--reference-evidence-storage-class"}
    for token in arguments:
        option = token.split("=", 1)[0]
        if not option.startswith("--") or not option.endswith("-storage-class"):
            continue
        if option in seen and option not in repeatable:
            raise SystemExit(f"duplicate storage declaration: {option}")
        seen.add(option)


def _validate_root_declarations(roots: list[SearchRoot]) -> None:
    aliases = tuple(item.alias for item in roots)
    if len(aliases) != len(set(aliases)):
        raise SystemExit("root aliases must be unique")


def _bind_reference_evidence(
    paths: list[tuple[str, Path]],
    classes: list[tuple[str, RootStorageClass]],
) -> tuple[ReferenceEvidenceInput, ...]:
    class_map = dict(classes)
    if len(class_map) != len(classes):
        raise SystemExit("duplicate reference-evidence storage declaration")
    path_keys = tuple(key for key, _ in paths)
    if len(set(path_keys)) != len(path_keys) or set(path_keys) != set(
        class_map
    ):
        raise SystemExit(
            "each --reference-evidence requires exactly one matching "
            "--reference-evidence-storage-class CITEKEY=CLASS"
        )
    return tuple(
        ReferenceEvidenceInput(key, path, class_map[key]) for key, path in paths
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="koios-ref")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("catalog-init")
    initialize.add_argument("catalog", type=Path)
    initialize.add_argument(
        "--catalog-storage-class", type=_storage_class, required=True
    )

    import_bib = commands.add_parser(
        "bib-import",
        help="observe BibTeX and import noncanonical candidates",
    )
    import_bib.add_argument("catalog", type=Path)
    import_bib.add_argument("bibliography", type=Path)
    import_bib.add_argument(
        "--catalog-storage-class", type=_storage_class, required=True
    )
    import_bib.add_argument(
        "--bibliography-storage-class", type=_storage_class, required=True
    )
    import_bib.add_argument("--source-id", required=True)
    import_bib.add_argument("--source-revision")
    import_bib.add_argument("--source-path")

    import_graph = commands.add_parser("graph-import")
    import_graph.add_argument("catalog", type=Path)
    import_graph.add_argument("sources", type=Path)
    import_graph.add_argument("nodes", type=Path)
    import_graph.add_argument("edges", type=Path)
    for name in ("catalog", "sources", "nodes", "edges"):
        import_graph.add_argument(
            f"--{name}-storage-class", type=_storage_class, required=True
        )

    summary = commands.add_parser("catalog-summary")
    summary.add_argument("catalog", type=Path)
    summary.add_argument(
        "--catalog-storage-class", type=_storage_class, required=True
    )

    reconcile = commands.add_parser(
        "collection-reconcile",
        help="project candidate evidence without canonical promotion",
    )
    reconcile.add_argument("bibliography", type=Path)
    reconcile.add_argument("corpus", type=Path)
    reconcile.add_argument("pdfs", type=Path)
    reconcile.add_argument("output", type=Path)
    reconcile.add_argument("--collection-id", required=True)
    reconcile.add_argument("--source-revision", required=True)
    reconcile.add_argument("--source-discovery", type=Path)
    reconcile.add_argument("--coverage-observation", type=Path)
    reconcile.add_argument("--acquisition-manifest", type=Path)
    reconcile.add_argument("--review-projection", type=Path)
    reconcile.add_argument("--catalog", type=Path)
    reconcile.add_argument("--asset-plan", type=Path)
    reconcile.add_argument(
        "--bibliography-storage-class", type=_storage_class, required=True
    )
    reconcile.add_argument(
        "--corpus-storage-class", type=_storage_class, required=True
    )
    reconcile.add_argument(
        "--output-storage-class", type=_storage_class, required=True
    )
    reconcile.add_argument(
        "--source-discovery-storage-class", type=_storage_class
    )
    reconcile.add_argument(
        "--coverage-observation-storage-class", type=_storage_class
    )
    reconcile.add_argument(
        "--acquisition-manifest-storage-class", type=_storage_class
    )
    reconcile.add_argument(
        "--review-projection-storage-class", type=_storage_class
    )
    reconcile.add_argument("--catalog-storage-class", type=_storage_class)
    reconcile.add_argument("--asset-plan-storage-class", type=_storage_class)
    reconcile.add_argument(
        "--pdf-storage-class",
        type=_storage_class,
        required=True,
    )
    reconcile.add_argument("--manuscript-root", type=Path)
    reconcile.add_argument(
        "--manuscript-storage-class",
        type=_storage_class,
    )
    reconcile.add_argument(
        "--reference-evidence-storage-class",
        action="append",
        type=_keyed_storage_class,
        default=[],
        metavar="CITEKEY=CLASS",
    )
    reconcile.add_argument(
        "--reference-evidence",
        action="append",
        type=_reference_evidence,
        default=[],
        metavar="CITEKEY=PATH",
        help=(
            "inject one canonical ingestion reference-evidence record; "
            "repeat for multiple managed PDFs"
        ),
    )

    scan = commands.add_parser(
        "assets-scan",
        help="match assets to proposed noncanonical citekeys",
    )
    scan.add_argument("bibliography", type=Path)
    scan.add_argument("output", type=Path)
    scan.add_argument(
        "--bibliography-storage-class", type=_storage_class, required=True
    )
    scan.add_argument(
        "--output-storage-class", type=_storage_class, required=True
    )
    scan.add_argument("--source-id", default="asset-scan")
    scan.add_argument(
        "--search-root", action="append", type=_root, required=True
    )

    apply_asset = commands.add_parser("assets-apply")
    apply_asset.add_argument("plan", type=Path)
    apply_asset.add_argument("citekey")
    apply_asset.add_argument("destination", type=Path)
    apply_asset.add_argument(
        "--plan-storage-class", type=_storage_class, required=True
    )
    apply_asset.add_argument(
        "--destination-storage-class", type=_storage_class, required=True
    )
    apply_asset.add_argument("--catalog-storage-class", type=_storage_class)
    apply_asset.add_argument(
        "--search-root", action="append", type=_root, required=True
    )
    apply_asset.add_argument("--candidate-path")
    apply_asset.add_argument("--authorization", type=Path, required=True)
    apply_asset.add_argument(
        "--authorization-storage-class", type=_storage_class, required=True
    )
    apply_asset.add_argument("--identity-projection", type=Path, required=True)
    apply_asset.add_argument(
        "--identity-projection-storage-class",
        type=_storage_class,
        required=True,
    )
    apply_asset.add_argument("--catalog", type=Path)
    apply_asset.add_argument("--rights-status", default="private-local")

    record_assets = commands.add_parser("assets-record-plan")
    record_assets.add_argument("catalog", type=Path)
    record_assets.add_argument("plan", type=Path)
    record_assets.add_argument(
        "--catalog-storage-class", type=_storage_class, required=True
    )
    record_assets.add_argument(
        "--plan-storage-class", type=_storage_class, required=True
    )
    record_assets.add_argument(
        "--rights-status", default="private-local-rights-unreviewed"
    )

    acquisition_create = commands.add_parser("acquisition-create")
    acquisition_create.add_argument("metadata", type=Path)
    acquisition_create.add_argument("output", type=Path)
    acquisition_create.add_argument(
        "--metadata-storage-class", type=_storage_class, required=True
    )
    acquisition_create.add_argument(
        "--output-storage-class", type=_storage_class, required=True
    )
    acquisition_create.add_argument("--source-id", required=True)
    acquisition_create.add_argument(
        "--source-root", action="append", type=_root, required=True
    )

    acquisition_verify = commands.add_parser("acquisition-verify")
    acquisition_verify.add_argument("manifest", type=Path)
    acquisition_verify.add_argument(
        "--manifest-storage-class", type=_storage_class, required=True
    )
    acquisition_verify.add_argument(
        "--source-root", action="append", type=_root, required=True
    )

    enrich = commands.add_parser("enrich-crossref")
    enrich.add_argument("doi")
    enrich.add_argument("--cache", type=Path)
    enrich.add_argument("--cache-storage-class", type=_storage_class)
    enrich.add_argument("--mailto")

    validate = commands.add_parser("validate")
    validate.add_argument("bibliography", type=Path)
    validate.add_argument("notes", type=Path)
    validate.add_argument("pdfs", type=Path)
    validate.add_argument(
        "--bibliography-storage-class", type=_storage_class, required=True
    )
    validate.add_argument(
        "--notes-storage-class",
        type=_storage_class,
        required=True,
    )
    validate.add_argument(
        "--pdf-storage-class",
        type=_storage_class,
        required=True,
    )
    validate.add_argument("--source-id", default="validation")
    return parser


def main(arguments: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
    _reject_duplicate_storage_options(raw_arguments)
    args = _parser().parse_args(raw_arguments)
    for attribute in ("search_root", "source_root"):
        if hasattr(args, attribute):
            _validate_root_declarations(getattr(args, attribute))
    if args.command == "collection-reconcile":
        _paired_storage_class(
            args.source_discovery,
            args.source_discovery_storage_class,
            label="source-discovery",
        )
        _paired_storage_class(
            args.coverage_observation,
            args.coverage_observation_storage_class,
            label="coverage-observation",
        )
        _paired_storage_class(
            args.acquisition_manifest,
            args.acquisition_manifest_storage_class,
            label="acquisition-manifest",
        )
        _paired_storage_class(
            args.review_projection,
            args.review_projection_storage_class,
            label="review-projection",
        )
        _paired_storage_class(
            args.catalog,
            args.catalog_storage_class,
            label="catalog",
        )
        _paired_storage_class(
            args.asset_plan,
            args.asset_plan_storage_class,
            label="asset-plan",
        )
        if (args.manuscript_root is None) != (
            args.manuscript_storage_class is None
        ):
            raise SystemExit(
                "--manuscript-root and --manuscript-storage-class must be "
                "supplied together"
            )
        _bind_reference_evidence(
            args.reference_evidence,
            args.reference_evidence_storage_class,
        )
    if args.command == "enrich-crossref" and (
        (args.cache is None) != (args.cache_storage_class is None)
    ):
        raise SystemExit(
            "--cache and --cache-storage-class must be supplied together"
        )
    if args.command == "catalog-init":
        ReferenceCatalog(
            args.catalog, storage_class=args.catalog_storage_class
        ).initialize()
        return 0
    if args.command == "bib-import":
        imported = load_bibliography(
            args.bibliography,
            source_id=args.source_id,
            storage_class=args.bibliography_storage_class,
            source_revision=args.source_revision,
            source_path=args.source_path,
        )
        catalog = ReferenceCatalog(
            args.catalog, storage_class=args.catalog_storage_class
        )
        catalog.initialize()
        catalog.import_candidates(
            imported.candidates,
            imported.observations,
        )
        print(
            json.dumps(
                {
                    "catalog_counts": catalog.counts(),
                    "coverage_status": "complete",
                    "effective_limits": imported.effective_limits.to_dict(),
                    "effective_limits_id": imported.effective_limits_id,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "graph-import":
        graph = load_candidate_graph(
            args.sources,
            args.nodes,
            args.edges,
            sources_storage_class=args.sources_storage_class,
            nodes_storage_class=args.nodes_storage_class,
            edges_storage_class=args.edges_storage_class,
        )
        catalog = ReferenceCatalog(
            args.catalog, storage_class=args.catalog_storage_class
        )
        catalog.initialize()
        catalog.import_citation_graph(graph)
        print(
            json.dumps(
                {
                    "catalog_counts": catalog.counts(),
                    "coverage_status": "complete",
                    "effective_limits": asdict(graph.effective_limits),
                    "effective_limits_id": graph.effective_limits.evidence_id,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "catalog-summary":
        catalog = ReferenceCatalog(
            args.catalog, storage_class=args.catalog_storage_class
        )
        print(json.dumps(catalog.counts(), indent=2))
        return 0
    if args.command == "collection-reconcile":
        imported = load_bibliography(
            args.bibliography,
            source_id=args.collection_id,
            storage_class=args.bibliography_storage_class,
            source_revision=args.source_revision,
        )
        bibliography_bytes = imported.bibliography_bytes
        source_discovery_storage = _paired_storage_class(
            args.source_discovery,
            args.source_discovery_storage_class,
            label="source-discovery",
        )
        coverage_storage = _paired_storage_class(
            args.coverage_observation,
            args.coverage_observation_storage_class,
            label="coverage-observation",
        )
        acquisition_storage = _paired_storage_class(
            args.acquisition_manifest,
            args.acquisition_manifest_storage_class,
            label="acquisition-manifest",
        )
        review_storage = _paired_storage_class(
            args.review_projection,
            args.review_projection_storage_class,
            label="review-projection",
        )
        catalog_storage = _paired_storage_class(
            args.catalog,
            args.catalog_storage_class,
            label="catalog",
        )
        asset_plan_storage = _paired_storage_class(
            args.asset_plan,
            args.asset_plan_storage_class,
            label="asset-plan",
        )
        if (
            args.manuscript_root is not None
            and args.manuscript_storage_class is None
        ):
            raise SystemExit(
                "--manuscript-storage-class is required with --manuscript-root"
            )
        citation_closure = (
            build_citation_closure(
                args.manuscript_root,
                storage_class=args.manuscript_storage_class,
                bibliography_keys=tuple(
                    sorted(
                        record.proposed_citekey
                        for record in imported.candidates
                    )
                ),
                source_revision=args.source_revision,
            )
            if args.manuscript_root is not None
            else None
        )
        managed_pdfs = scan_managed_pdfs(
            args.pdfs,
            storage_class=args.pdf_storage_class,
            source_discovery=args.source_discovery,
            source_discovery_storage_class=(
                source_discovery_storage
                if args.source_discovery is not None
                else None
            ),
        )
        processing_evidence = (
            load_ingestion_reference_evidence(
                _bind_reference_evidence(
                    args.reference_evidence,
                    args.reference_evidence_storage_class,
                ),
                managed_pdfs=managed_pdfs,
            )
            if args.reference_evidence
            else None
        )
        coverage_observation_bytes = (
            read_path_bytes(
                args.coverage_observation,
                label="coverage observation",
                root_alias="coverage-observation",
                storage_class=coverage_storage,
                max_bytes=_required_limit(
                    RECONCILIATION_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
            if args.coverage_observation is not None
            and coverage_storage is not None
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
                    args.acquisition_manifest,
                    label="acquisition manifest",
                    root_alias="acquisition-manifest",
                    storage_class=acquisition_storage,
                    max_bytes=_required_limit(
                        ACQUISITION_IO_LIMITS.max_json_bytes,
                        "max_json_bytes",
                    ),
                )
            )
            if args.acquisition_manifest is not None
            and acquisition_storage is not None
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
                    args.review_projection,
                    label="review projection",
                    root_alias="review-projection",
                    storage_class=review_storage,
                    max_bytes=_required_limit(
                        REVIEW_IO_LIMITS.max_json_bytes,
                        "max_json_bytes",
                    ),
                )
            )
            if args.review_projection is not None and review_storage is not None
            else None
        )
        catalog_assets = None
        if args.catalog is not None and catalog_storage is not None:
            grouped_assets: dict[str, list[SourceAssetRecord]] = {}
            for asset in ReferenceCatalog(
                args.catalog,
                storage_class=catalog_storage,
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
                    args.asset_plan,
                    label="asset discovery plan",
                    root_alias="asset-plan-input",
                    storage_class=asset_plan_storage,
                    max_bytes=_required_limit(
                        ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                        "max_json_bytes",
                    ),
                )
            )
            if args.asset_plan is not None and asset_plan_storage is not None
            else None
        )
        outputs = reconcile_collection(
            imported.candidates,
            bibliography_bytes=bibliography_bytes,
            collection_id=args.collection_id,
            source_revision=args.source_revision,
            collection_rows=load_collection_rows(
                args.corpus, storage_class=args.corpus_storage_class
            ),
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
        publication = publish_reconciliation(
            outputs,
            output_directory=args.output,
            output_storage_class=args.output_storage_class,
        )
        print(
            json.dumps(
                {
                    "status": publication.status,
                    "package_id": publication.package_id,
                    "output_directory": str(publication.output_directory),
                    "counts": dict(outputs.manifest.counts),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "assets-scan":
        imported = load_bibliography(
            args.bibliography,
            source_id=args.source_id,
            storage_class=args.bibliography_storage_class,
        )
        plan = AssetDiscoveryPlanner().scan(
            imported.candidates,
            tuple(args.search_root),
        )
        write_path_bytes(
            args.output,
            plan.to_json().encode("utf-8"),
            label="asset discovery plan",
            root_alias="asset-plan-output",
            storage_class=args.output_storage_class,
            replace=True,
        )
        print(f"wrote {len(plan.candidates)} candidates to {args.output}")
        return 0
    if args.command == "assets-apply":
        if (args.catalog is None) != (args.catalog_storage_class is None):
            raise SystemExit(
                "--catalog and --catalog-storage-class must be supplied "
                "together"
            )
        plan = AssetDiscoveryPlan.from_json(
            read_path_text(
                args.plan,
                label="asset discovery plan",
                root_alias="asset-plan-input",
                storage_class=args.plan_storage_class,
                max_bytes=_required_limit(
                    ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
        )
        authorization = CanonicalAssetAuthorization.from_json(
            read_path_text(
                args.authorization,
                label="canonical asset authorization",
                root_alias="asset-authorization-input",
                storage_class=args.authorization_storage_class,
                max_bytes=_required_limit(
                    ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
        )
        identity_projection = IdentityProjection.from_json(
            read_path_text(
                args.identity_projection,
                label="identity projection",
                root_alias="identity-projection-input",
                storage_class=args.identity_projection_storage_class,
                max_bytes=_required_limit(
                    ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
        )
        matches = [
            item
            for item in plan.candidates
            if item.observation_id
            == authorization.selected_asset_observation_id
            and item.proposed_citekey == args.citekey
            and (
                args.candidate_path is None
                or item.relative_path == args.candidate_path
            )
        ]
        if len(matches) != 1:
            raise SystemExit(
                "authorization must select exactly one matching asset"
            )
        candidate = matches[0]
        expected_root_preflight = next(
            item
            for item in plan.root_preflights
            if item.root_alias == candidate.root_alias
        )
        catalog_record = SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.identity_status,
            citekey_status=candidate.citekey_status,
            sha256=candidate.sha256,
            byte_size=candidate.byte_size,
            root_alias="materialized-assets",
            relative_path=f"{authorization.canonical_citekey}.pdf",
            rights_status=args.rights_status,
            asset_status="authorized-canonical-local-copy",
        )
        recording: AbstractContextManager[None] = nullcontext()
        if args.catalog is not None:
            catalog = ReferenceCatalog(
                args.catalog, storage_class=args.catalog_storage_class
            )
            catalog.initialize()
            recording = catalog.source_asset_recording_transaction(
                catalog_record
            )
        materialization_result: AssetMaterializationResult | None = None
        try:
            with recording:
                materialization_result = materialize_asset_with_result(
                    candidate,
                    authorization=authorization,
                    plan=plan,
                    identity_projection=identity_projection,
                    expected_root_preflight=expected_root_preflight,
                    roots=tuple(args.search_root),
                    destination_directory=args.destination,
                    destination_storage_class=args.destination_storage_class,
                )
        except Exception as error:
            if (
                materialization_result is not None
                and materialization_result.created
            ):
                try:
                    rollback_materialized_asset(
                        materialization_result,
                        candidate=candidate,
                        authorization=authorization,
                        destination_directory=args.destination,
                        destination_storage_class=(
                            args.destination_storage_class
                        ),
                    )
                except Exception as rollback_error:
                    raise ExceptionGroup(
                        "catalog recording failed and exact asset rollback "
                        "also failed",
                        (error, rollback_error),
                    ) from error
            raise
        if materialization_result is None:  # pragma: no cover
            raise RuntimeError("asset materialization produced no result")
        print(materialization_result.path)
        return 0
    if args.command == "assets-record-plan":
        plan = AssetDiscoveryPlan.from_json(
            read_path_text(
                args.plan,
                label="asset discovery plan",
                root_alias="asset-plan-input",
                storage_class=args.plan_storage_class,
                max_bytes=_required_limit(
                    ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
        )
        assets = tuple(
            SourceAssetRecord(
                candidate_id=candidate.candidate_id,
                proposed_citekey=candidate.proposed_citekey,
                identity_status=candidate.identity_status,
                citekey_status=candidate.citekey_status,
                sha256=candidate.sha256,
                byte_size=candidate.byte_size,
                root_alias=candidate.root_alias,
                relative_path=candidate.relative_path,
                rights_status=args.rights_status,
                asset_status="unresolved-heuristic-observation",
            )
            for candidate in plan.candidates
        )
        catalog = ReferenceCatalog(
            args.catalog, storage_class=args.catalog_storage_class
        )
        catalog.initialize()
        catalog.record_source_assets(assets)
        return 0
    if args.command == "acquisition-create":
        rows = _bounded_csv_rows(
            args.metadata,
            label="acquisition metadata",
            storage_class=args.metadata_storage_class,
            limits=ACQUISITION_IO_LIMITS,
        )
        manifest = create_acquisition_manifest(
            source_id=args.source_id,
            rows=rows,
            roots=tuple(args.source_root),
        )
        acquisition_publication = publish_acquisition_manifest(
            manifest,
            output_path=args.output,
            output_storage_class=args.output_storage_class,
        )
        print(
            json.dumps(
                {
                    "status": acquisition_publication.status,
                    "manifest_id": acquisition_publication.manifest_id,
                    "entries": len(manifest.entries),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "acquisition-verify":
        manifest = AcquisitionManifest.from_json(
            read_path_text(
                args.manifest,
                label="acquisition manifest",
                root_alias="acquisition-manifest-input",
                storage_class=args.manifest_storage_class,
                max_bytes=_required_limit(
                    ACQUISITION_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
        )
        verify_acquisition_manifest(
            manifest,
            roots=tuple(args.source_root),
        )
        print(
            json.dumps(
                {
                    "schema_version": manifest.schema_version,
                    "manifest_id": manifest.manifest_id,
                    "normalized_input_id": manifest.normalized_input_id,
                    "contract_id": manifest.contract_id,
                    "contract_status": manifest.contract_status,
                    "source_id": manifest.source_id,
                    "verified": len(manifest.entries),
                    "coverage_status": manifest.coverage_status,
                    "effective_limits": manifest.effective_limits.to_dict(),
                    "effective_limits_id": manifest.effective_limits_id,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "enrich-crossref":
        result = CrossrefClient(
            mailto=args.mailto,
            cache_directory=args.cache,
            cache_storage_class=args.cache_storage_class,
        ).fetch(args.doi)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        imported = load_bibliography(
            args.bibliography,
            source_id=args.source_id,
            storage_class=args.bibliography_storage_class,
        )
        issues = validate_reference_objects(
            imported.candidates,
            notes_directory=args.notes,
            notes_storage_class=args.notes_storage_class,
            pdf_directory=args.pdfs,
            pdf_storage_class=args.pdf_storage_class,
        )
        for issue in issues:
            print(f"{issue.code}: {issue.path}: {issue.message}")
        return 1 if issues else 0
    raise AssertionError(f"unhandled command: {args.command}")


def _bounded_csv_rows(
    path: Path,
    *,
    label: str,
    storage_class: RootStorageClass,
    limits: ReferenceIOLimits,
) -> tuple[dict[str, str], ...]:
    max_csv_bytes = _required_limit(limits.max_csv_bytes, "max_csv_bytes")
    try:
        text = read_path_text(
            path,
            label=label,
            root_alias=label.replace(" ", "-"),
            storage_class=storage_class,
            max_bytes=max_csv_bytes,
        )
    except PathLimitError as error:
        raise ReferenceIOLimitError(
            resource=error.resource,
            limit_name="max_csv_bytes",
            limit=max_csv_bytes,
            observed=error.observed,
            limits=limits,
        ) from error
    max_rows = _required_limit(limits.max_rows, "max_rows")
    max_text_bytes = _required_limit(
        limits.max_text_bytes,
        "max_text_bytes",
    )
    rows: list[dict[str, str]] = []
    try:
        with bounded_csv_field_size(max_text_bytes):
            reader = csv.DictReader(io.StringIO(text, newline=""))
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise ValueError(f"{label} CSV has no header")
            if any(not field or not field.strip() for field in fieldnames):
                raise ValueError(f"{label} CSV has an empty header")
            if len(fieldnames) != len(set(fieldnames)):
                raise ValueError(f"{label} CSV has duplicate headers")
            for row_number, row in enumerate(reader, start=1):
                if row_number > max_rows:
                    raise ReferenceIOLimitError(
                        resource=label,
                        limit_name="max_rows",
                        limit=max_rows,
                        observed=row_number,
                        limits=limits,
                    )
                if None in row:
                    raise ValueError(
                        f"{label} CSV row {row_number} has surplus fields"
                    )
                normalized = {
                    str(key): str(value)
                    for key, value in row.items()
                    if value is not None
                }
                for field_name, field_value in normalized.items():
                    field_bytes = bounded_utf8_size(
                        field_value,
                        max_bytes=max_text_bytes,
                    )
                    if field_bytes > max_text_bytes:
                        raise ReferenceIOLimitError(
                            resource=(
                                f"{label} row {row_number} field {field_name}"
                            ),
                            limit_name="max_text_bytes",
                            limit=max_text_bytes,
                            observed=field_bytes,
                            limits=limits,
                        )
                rows.append(normalized)
    except csv.Error as error:
        if "field larger than field limit" in str(error):
            raise ReferenceIOLimitError(
                resource=f"{label} CSV field",
                limit_name="max_text_bytes",
                limit=max_text_bytes,
                observed=max_text_bytes + 1,
                limits=limits,
            ) from error
        raise ValueError(f"{label} CSV is malformed") from error
    return tuple(rows)


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"command I/O profile must define {name}")
    return value
