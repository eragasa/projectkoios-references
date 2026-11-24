"""Thin operator adapter for projectkoios.references domain objects."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

from projectkoios.references.acquisition import (
    AcquisitionManifest,
    create_acquisition_manifest,
    publish_acquisition_manifest,
    verify_acquisition_manifest,
)
from projectkoios.references.asset.application.action import (
    AssetApplicationOperation,
)
from projectkoios.references.asset.application.error import (
    AssetApplicationError,
)
from projectkoios.references.asset.application.request import (
    AssetApplicationOperationRequest,
)
from projectkoios.references.assets import (
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    SearchRoot,
)
from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.citation.closure import CitationScanMode
from projectkoios.references.citation.draft import (
    CITATION_DRAFT_MAX_BYTES,
    CitationDraftParser,
    CitationDraftParseRequest,
    CitationDraftRenderer,
    CitationDraftRenderRequest,
)
from projectkoios.references.collections.reconciliation.operation import (
    CollectionReconciliationOperation,
    CollectionReconciliationOperationRequest,
)
from projectkoios.references.enrichment import CrossrefClient
from projectkoios.references.graph import load_candidate_graph
from projectkoios.references.ingestion_evidence import ReferenceEvidenceInput
from projectkoios.references.io_limits import (
    ACQUISITION_IO_LIMITS,
    ASSET_DISCOVERY_IO_LIMITS,
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
from projectkoios.references.validation import validate_reference_objects


class ReferencesOperatorAdapter:
    """Translate operator CLI input into canonical package calls."""

    @staticmethod
    def parse_search_root(value: str) -> SearchRoot:
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

    @staticmethod
    def parse_storage_class(value: str) -> RootStorageClass:
        try:
            return RootStorageClass(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                "storage class must be local or cloud-backed"
            ) from error

    @staticmethod
    def parse_reference_evidence_path(value: str) -> tuple[str, Path]:
        citekey, separator, raw_path = value.partition("=")
        if not separator or not citekey or not raw_path:
            raise argparse.ArgumentTypeError(
                "reference evidence must be CITEKEY=PATH"
            )
        try:
            return citekey, Path(raw_path).expanduser()
        except (TypeError, ValueError) as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    @staticmethod
    def parse_keyed_storage_class(value: str) -> tuple[str, RootStorageClass]:
        key, separator, raw_class = value.partition("=")
        if not separator or not key:
            raise argparse.ArgumentTypeError(
                "keyed storage class must be KEY=local or KEY=cloud-backed"
            )
        return key, ReferencesOperatorAdapter.parse_storage_class(raw_class)

    @staticmethod
    def reject_duplicate_storage_options(arguments: list[str]) -> None:
        seen: set[str] = set()
        repeatable = {"--reference-evidence-storage-class"}
        for token in arguments:
            option = token.split("=", 1)[0]
            if not option.startswith("--") or not option.endswith(
                "-storage-class"
            ):
                continue
            if option in seen and option not in repeatable:
                raise SystemExit(f"duplicate storage declaration: {option}")
            seen.add(option)

    @staticmethod
    def validate_root_declarations(roots: list[SearchRoot]) -> None:
        aliases = tuple(item.alias for item in roots)
        if len(aliases) != len(set(aliases)):
            raise SystemExit("root aliases must be unique")

    @staticmethod
    def bind_reference_evidence(
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
            ReferenceEvidenceInput(key, path, class_map[key])
            for key, path in paths
        )

    @staticmethod
    def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="koios-ref")
        commands = parser.add_subparsers(dest="command", required=True)

        initialize = commands.add_parser("catalog-init")
        initialize.add_argument("catalog", type=Path)
        initialize.add_argument(
            "--catalog-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )

        import_bib = commands.add_parser(
            "bib-import",
            help="observe BibTeX and import noncanonical candidates",
        )
        import_bib.add_argument("catalog", type=Path)
        import_bib.add_argument("bibliography", type=Path)
        import_bib.add_argument(
            "--catalog-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        import_bib.add_argument(
            "--bibliography-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        import_bib.add_argument("--source-id", required=True)
        import_bib.add_argument("--source-revision")
        import_bib.add_argument("--source-path")

        render_bib = commands.add_parser(
            "bib-render",
            help="render bounded noncanonical citation drafts as BibTeX",
        )
        render_bib.add_argument("metadata", type=Path)
        render_bib.add_argument("output", type=Path)
        render_bib.add_argument(
            "--metadata-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        render_bib.add_argument(
            "--output-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )

        import_graph = commands.add_parser("graph-import")
        import_graph.add_argument("catalog", type=Path)
        import_graph.add_argument("sources", type=Path)
        import_graph.add_argument("nodes", type=Path)
        import_graph.add_argument("edges", type=Path)
        for name in ("catalog", "sources", "nodes", "edges"):
            import_graph.add_argument(
                f"--{name}-storage-class",
                type=ReferencesOperatorAdapter.parse_storage_class,
                required=True,
            )

        summary = commands.add_parser("catalog-summary")
        summary.add_argument("catalog", type=Path)
        summary.add_argument(
            "--catalog-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
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
            "--bibliography-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        reconcile.add_argument(
            "--corpus-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        reconcile.add_argument(
            "--output-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        reconcile.add_argument(
            "--source-discovery-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--coverage-observation-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--acquisition-manifest-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--review-projection-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--catalog-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--asset-plan-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--pdf-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        reconcile.add_argument("--manuscript-root", type=Path)
        reconcile.add_argument(
            "--manuscript-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        reconcile.add_argument(
            "--manuscript-mode",
            type=CitationScanMode,
            choices=tuple(CitationScanMode),
        )
        reconcile.add_argument("--manuscript-entrypoint")
        reconcile.add_argument(
            "--reference-evidence-storage-class",
            action="append",
            type=ReferencesOperatorAdapter.parse_keyed_storage_class,
            default=[],
            metavar="CITEKEY=CLASS",
        )
        reconcile.add_argument(
            "--reference-evidence",
            action="append",
            type=ReferencesOperatorAdapter.parse_reference_evidence_path,
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
            "--bibliography-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        scan.add_argument(
            "--output-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        scan.add_argument("--source-id", default="asset-scan")
        scan.add_argument(
            "--search-root",
            action="append",
            type=ReferencesOperatorAdapter.parse_search_root,
            required=True,
        )

        apply_asset = commands.add_parser("assets-apply")
        apply_asset.add_argument("plan", type=Path)
        apply_asset.add_argument("citekey")
        apply_asset.add_argument("destination", type=Path)
        apply_asset.add_argument(
            "--plan-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        apply_asset.add_argument(
            "--destination-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        apply_asset.add_argument(
            "--catalog-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        apply_asset.add_argument(
            "--search-root",
            action="append",
            type=ReferencesOperatorAdapter.parse_search_root,
            required=True,
        )
        apply_asset.add_argument("--candidate-path")
        apply_asset.add_argument("--authorization", type=Path, required=True)
        apply_asset.add_argument(
            "--authorization-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        apply_asset.add_argument(
            "--identity-projection", type=Path, required=True
        )
        apply_asset.add_argument(
            "--identity-projection-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        apply_asset.add_argument("--catalog", type=Path)
        apply_asset.add_argument("--rights-status", default="private-local")

        record_assets = commands.add_parser("assets-record-plan")
        record_assets.add_argument("catalog", type=Path)
        record_assets.add_argument("plan", type=Path)
        record_assets.add_argument(
            "--catalog-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        record_assets.add_argument(
            "--plan-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        record_assets.add_argument(
            "--rights-status", default="private-local-rights-unreviewed"
        )

        acquisition_create = commands.add_parser("acquisition-create")
        acquisition_create.add_argument("metadata", type=Path)
        acquisition_create.add_argument("output", type=Path)
        acquisition_create.add_argument(
            "--metadata-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        acquisition_create.add_argument(
            "--output-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        acquisition_create.add_argument("--source-id", required=True)
        acquisition_create.add_argument(
            "--source-root",
            action="append",
            type=ReferencesOperatorAdapter.parse_search_root,
            required=True,
        )

        acquisition_verify = commands.add_parser("acquisition-verify")
        acquisition_verify.add_argument("manifest", type=Path)
        acquisition_verify.add_argument(
            "--manifest-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        acquisition_verify.add_argument(
            "--source-root",
            action="append",
            type=ReferencesOperatorAdapter.parse_search_root,
            required=True,
        )

        enrich = commands.add_parser("enrich-crossref")
        enrich.add_argument("doi")
        enrich.add_argument("--cache", type=Path)
        enrich.add_argument(
            "--cache-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
        )
        enrich.add_argument("--mailto")

        validate = commands.add_parser("validate")
        validate.add_argument("bibliography", type=Path)
        validate.add_argument("notes", type=Path)
        validate.add_argument("pdfs", type=Path)
        validate.add_argument(
            "--bibliography-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        validate.add_argument(
            "--notes-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        validate.add_argument(
            "--pdf-storage-class",
            type=ReferencesOperatorAdapter.parse_storage_class,
            required=True,
        )
        validate.add_argument("--source-id", default="validation")
        return parser

    @staticmethod
    def run(arguments: list[str] | None = None) -> int:
        raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
        ReferencesOperatorAdapter.reject_duplicate_storage_options(
            raw_arguments
        )
        args = ReferencesOperatorAdapter.build_parser().parse_args(
            raw_arguments
        )
        for attribute in ("search_root", "source_root"):
            if hasattr(args, attribute):
                ReferencesOperatorAdapter.validate_root_declarations(
                    getattr(args, attribute)
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
        if args.command == "bib-render":
            metadata = read_path_bytes(
                args.metadata,
                label="citation draft metadata",
                root_alias="citation-draft-metadata",
                storage_class=args.metadata_storage_class,
                max_bytes=CITATION_DRAFT_MAX_BYTES,
            )
            parsed = CitationDraftParser().parse(
                request=CitationDraftParseRequest(content=metadata)
            )
            entries = parsed.entries
            bibliography = (
                CitationDraftRenderer()
                .render(request=CitationDraftRenderRequest(entries=entries))
                .bibliography
            )
            write_path_bytes(
                args.output,
                bibliography,
                label="rendered citation draft",
                root_alias="rendered-citation-draft",
                storage_class=args.output_storage_class,
                replace=False,
            )
            print(
                json.dumps(
                    {
                        "authority": "proposed-noncanonical",
                        "entry_count": len(entries),
                        "output_sha256": hashlib.sha256(
                            bibliography
                        ).hexdigest(),
                    },
                    indent=2,
                )
            )
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
                        "effective_limits_id": (
                            graph.effective_limits.evidence_id
                        ),
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
            evidence = ReferencesOperatorAdapter.bind_reference_evidence(
                args.reference_evidence,
                args.reference_evidence_storage_class,
            )
            try:
                request = CollectionReconciliationOperationRequest(
                    bibliography=args.bibliography,
                    bibliography_storage_class=(
                        args.bibliography_storage_class
                    ),
                    corpus=args.corpus,
                    corpus_storage_class=args.corpus_storage_class,
                    pdfs=args.pdfs,
                    pdf_storage_class=args.pdf_storage_class,
                    output_directory=args.output,
                    output_storage_class=args.output_storage_class,
                    collection_id=args.collection_id,
                    source_revision=args.source_revision,
                    source_discovery=args.source_discovery,
                    source_discovery_storage_class=(
                        args.source_discovery_storage_class
                    ),
                    coverage_observation=args.coverage_observation,
                    coverage_observation_storage_class=(
                        args.coverage_observation_storage_class
                    ),
                    acquisition_manifest=args.acquisition_manifest,
                    acquisition_manifest_storage_class=(
                        args.acquisition_manifest_storage_class
                    ),
                    review_projection=args.review_projection,
                    review_projection_storage_class=(
                        args.review_projection_storage_class
                    ),
                    catalog=args.catalog,
                    catalog_storage_class=args.catalog_storage_class,
                    asset_plan=args.asset_plan,
                    asset_plan_storage_class=args.asset_plan_storage_class,
                    manuscript_root=args.manuscript_root,
                    manuscript_storage_class=args.manuscript_storage_class,
                    manuscript_mode=args.manuscript_mode,
                    manuscript_entrypoint=args.manuscript_entrypoint,
                    reference_evidence=evidence,
                )
            except (TypeError, ValueError) as error:
                raise SystemExit(str(error)) from error
            operation_result = CollectionReconciliationOperation().action(
                request=request
            )
            publication = operation_result.publication.publication
            outputs = operation_result.reconciliation.outputs
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
                replace=False,
            )
            print(f"wrote {len(plan.candidates)} candidates to {args.output}")
            return 0
        if args.command == "assets-apply":
            try:
                request = AssetApplicationOperationRequest(
                    plan=args.plan,
                    plan_storage_class=args.plan_storage_class,
                    authorization=args.authorization,
                    authorization_storage_class=(
                        args.authorization_storage_class
                    ),
                    identity_projection=args.identity_projection,
                    identity_projection_storage_class=(
                        args.identity_projection_storage_class
                    ),
                    citekey=args.citekey,
                    candidate_path=args.candidate_path,
                    search_roots=tuple(args.search_root),
                    destination=args.destination,
                    destination_storage_class=(args.destination_storage_class),
                    rights_status=args.rights_status,
                    catalog=args.catalog,
                    catalog_storage_class=args.catalog_storage_class,
                )
            except (TypeError, ValueError) as error:
                raise SystemExit(str(error)) from error
            try:
                application_result = AssetApplicationOperation().action(
                    request=request
                )
            except AssetApplicationError as error:
                raise SystemExit(str(error)) from error
            print(application_result.materialization.path)
            return 0
        if args.command == "assets-record-plan":
            plan = AssetDiscoveryPlan.from_json(
                read_path_text(
                    args.plan,
                    label="asset discovery plan",
                    root_alias="asset-plan-input",
                    storage_class=args.plan_storage_class,
                    max_bytes=ReferencesOperatorAdapter.require_limit(
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
            rows = ReferencesOperatorAdapter.read_bounded_csv_rows(
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
                    max_bytes=ReferencesOperatorAdapter.require_limit(
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

    @staticmethod
    def read_bounded_csv_rows(
        path: Path,
        *,
        label: str,
        storage_class: RootStorageClass,
        limits: ReferenceIOLimits,
    ) -> tuple[dict[str, str], ...]:
        max_csv_bytes = ReferencesOperatorAdapter.require_limit(
            limits.max_csv_bytes, "max_csv_bytes"
        )
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
        max_rows = ReferencesOperatorAdapter.require_limit(
            limits.max_rows, "max_rows"
        )
        max_text_bytes = ReferencesOperatorAdapter.require_limit(
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
                                    f"{label} row {row_number} field "
                                    f"{field_name}"
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

    @staticmethod
    def require_limit(value: int | None, name: str) -> int:
        if value is None:
            raise ValueError(f"command I/O profile must define {name}")
        return value


def main(arguments: list[str] | None = None) -> int:
    """Run the repository operator adapter."""
    return ReferencesOperatorAdapter.run(arguments)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
