from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import asdict
from pathlib import Path

from projectkoios.references.acquisition import (
    AcquisitionManifest,
    create_acquisition_manifest,
    verify_acquisition_manifest,
)
from projectkoios.references.assets import (
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.collection_reconciliation import (
    build_citation_closure,
    load_collection_rows,
    publish_reconciliation,
    reconcile_collection,
    scan_managed_pdfs,
    scan_processing_evidence,
)
from projectkoios.references.coverage import CoverageObservation
from projectkoios.references.enrichment import CrossrefClient
from projectkoios.references.graph import load_candidate_graph
from projectkoios.references.models import (
    ReferenceAlias,
    ReviewMembership,
    ReviewStatus,
    SourceAssetRecord,
)
from projectkoios.references.path_safety import (
    read_path_bytes,
    read_path_text,
    write_path_bytes,
)
from projectkoios.references.validation import validate_reference_objects


def _root(value: str) -> SearchRoot:
    alias, separator, raw_path = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("search root must be ALIAS=PATH")
    return SearchRoot(alias, Path(raw_path).expanduser())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="koios-ref")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("catalog-init")
    initialize.add_argument("catalog", type=Path)

    import_bib = commands.add_parser("bib-import")
    import_bib.add_argument("catalog", type=Path)
    import_bib.add_argument("bibliography", type=Path)
    import_bib.add_argument("--source-id", required=True)
    import_bib.add_argument("--source-revision")
    import_bib.add_argument("--source-path")

    import_graph = commands.add_parser("graph-import")
    import_graph.add_argument("catalog", type=Path)
    import_graph.add_argument("nodes", type=Path)
    import_graph.add_argument("edges", type=Path)

    summary = commands.add_parser("catalog-summary")
    summary.add_argument("catalog", type=Path)

    alias = commands.add_parser("alias-add")
    alias.add_argument("catalog", type=Path)
    alias.add_argument("alias")
    alias.add_argument("canonical_citekey")
    alias.add_argument("--rationale", required=True)

    review = commands.add_parser("review-set")
    review.add_argument("catalog", type=Path)
    review.add_argument("collection_id")
    review.add_argument("citekey")
    review.add_argument("status", choices=tuple(ReviewStatus))
    review.add_argument("--decision-note")

    review_import = commands.add_parser("review-import")
    review_import.add_argument("catalog", type=Path)
    review_import.add_argument("collection_id")
    review_import.add_argument("corpus", type=Path)
    review_import.add_argument(
        "--status", choices=tuple(ReviewStatus), default="discovered"
    )

    reconcile = commands.add_parser("collection-reconcile")
    reconcile.add_argument("bibliography", type=Path)
    reconcile.add_argument("corpus", type=Path)
    reconcile.add_argument("pdfs", type=Path)
    reconcile.add_argument("output", type=Path)
    reconcile.add_argument("--collection-id", required=True)
    reconcile.add_argument("--source-revision", required=True)
    reconcile.add_argument("--source-discovery", type=Path)
    reconcile.add_argument("--coverage-observation", type=Path)
    reconcile.add_argument("--manuscript-root", type=Path)
    reconcile.add_argument("--ingestion-root", type=Path)

    scan = commands.add_parser("assets-scan")
    scan.add_argument("bibliography", type=Path)
    scan.add_argument("output", type=Path)
    scan.add_argument("--source-id", default="asset-scan")
    scan.add_argument(
        "--search-root", action="append", type=_root, required=True
    )

    apply_asset = commands.add_parser("assets-apply")
    apply_asset.add_argument("plan", type=Path)
    apply_asset.add_argument("citekey")
    apply_asset.add_argument("destination", type=Path)
    apply_asset.add_argument(
        "--search-root", action="append", type=_root, required=True
    )
    apply_asset.add_argument("--candidate-path")
    apply_asset.add_argument("--catalog", type=Path)
    apply_asset.add_argument("--rights-status", default="private-local")

    record_assets = commands.add_parser("assets-record-plan")
    record_assets.add_argument("catalog", type=Path)
    record_assets.add_argument("plan", type=Path)
    record_assets.add_argument(
        "--rights-status", default="private-local-rights-unreviewed"
    )
    record_assets.add_argument("--asset-status", default="located-local-copy")

    acquisition_create = commands.add_parser("acquisition-create")
    acquisition_create.add_argument("metadata", type=Path)
    acquisition_create.add_argument("output", type=Path)
    acquisition_create.add_argument("--source-id", required=True)
    acquisition_create.add_argument(
        "--source-root", action="append", type=_root, required=True
    )

    acquisition_verify = commands.add_parser("acquisition-verify")
    acquisition_verify.add_argument("manifest", type=Path)
    acquisition_verify.add_argument(
        "--source-root", action="append", type=_root, required=True
    )

    enrich = commands.add_parser("enrich-crossref")
    enrich.add_argument("doi")
    enrich.add_argument("--cache", type=Path)
    enrich.add_argument("--mailto")

    validate = commands.add_parser("validate")
    validate.add_argument("bibliography", type=Path)
    validate.add_argument("notes", type=Path)
    validate.add_argument("pdfs", type=Path)
    validate.add_argument("--source-id", default="validation")
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    if args.command == "catalog-init":
        ReferenceCatalog(args.catalog).initialize()
        return 0
    if args.command == "bib-import":
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        imported = load_bibliography(
            args.bibliography,
            source_id=args.source_id,
            source_revision=args.source_revision,
            source_path=args.source_path,
        )
        catalog.import_bibliography(imported.records, imported.occurrences)
        print(json.dumps(catalog.counts(), indent=2))
        return 0
    if args.command == "graph-import":
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        candidates, edges = load_candidate_graph(args.nodes, args.edges)
        catalog.import_citation_graph(candidates, edges)
        print(json.dumps(catalog.counts(), indent=2))
        return 0
    if args.command == "catalog-summary":
        print(json.dumps(ReferenceCatalog(args.catalog).counts(), indent=2))
        return 0
    if args.command == "alias-add":
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        catalog.add_alias(
            ReferenceAlias(
                alias=args.alias,
                canonical_citekey=args.canonical_citekey,
                rationale=args.rationale,
            )
        )
        return 0
    if args.command == "review-set":
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        catalog.set_review_membership(
            ReviewMembership(
                collection_id=args.collection_id,
                citekey=args.citekey,
                status=ReviewStatus(args.status),
                decision_note=args.decision_note,
            )
        )
        return 0
    if args.command == "review-import":
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        stream = io.StringIO(
            read_path_text(args.corpus, label="review corpus"),
            newline="",
        )
        rows = tuple(csv.DictReader(stream))
        for row in rows:
            citekey = row.get("citekey")
            if not citekey:
                raise ValueError(
                    "review corpus must contain non-empty citekeys"
                )
            catalog.set_review_membership(
                ReviewMembership(
                    collection_id=args.collection_id,
                    citekey=citekey,
                    status=ReviewStatus(args.status),
                )
            )
        return 0
    if args.command == "collection-reconcile":
        bibliography_bytes = read_path_bytes(
            args.bibliography,
            label="bibliography",
        )
        imported = load_bibliography(
            args.bibliography,
            source_id=args.collection_id,
            source_revision=args.source_revision,
        )
        citation_closure = (
            build_citation_closure(
                args.manuscript_root,
                bibliography_keys=tuple(
                    sorted(record.citekey for record in imported.records)
                ),
                source_revision=args.source_revision,
            )
            if args.manuscript_root is not None
            else None
        )
        managed_pdfs = scan_managed_pdfs(
            args.pdfs,
            source_discovery=args.source_discovery,
        )
        processing_evidence = (
            scan_processing_evidence(
                args.ingestion_root,
                citekeys=tuple(record.citekey for record in imported.records)
                + tuple(pdf.citekey for pdf in managed_pdfs),
            )
            if args.ingestion_root is not None
            else None
        )
        coverage_observation = (
            CoverageObservation.from_json(
                read_path_text(
                    args.coverage_observation,
                    label="coverage observation",
                )
            )
            if args.coverage_observation is not None
            else None
        )
        outputs = reconcile_collection(
            imported.records,
            bibliography_bytes=bibliography_bytes,
            collection_id=args.collection_id,
            source_revision=args.source_revision,
            collection_rows=load_collection_rows(args.corpus),
            managed_pdfs=managed_pdfs,
            citation_closure=citation_closure,
            coverage_observation=coverage_observation,
            processing_evidence=processing_evidence,
        )
        publication = publish_reconciliation(
            outputs,
            output_directory=args.output,
        )
        print(
            json.dumps(
                {
                    "status": publication.status,
                    "manifest_id": publication.manifest_id,
                    "output_directory": str(publication.output_directory),
                    "counts": outputs.manifest.counts,
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
        )
        plan = AssetDiscoveryPlanner().scan(
            imported.records,
            tuple(args.search_root),
        )
        write_path_bytes(
            args.output,
            plan.to_json().encode("utf-8"),
            label="asset discovery plan",
            replace=True,
        )
        print(f"wrote {len(plan.candidates)} candidates to {args.output}")
        return 0
    if args.command == "assets-apply":
        plan = AssetDiscoveryPlan.from_json(
            read_path_text(args.plan, label="asset discovery plan")
        )
        matches = [
            item
            for item in plan.candidates
            if item.citekey == args.citekey
            and (
                args.candidate_path is None
                or item.relative_path == args.candidate_path
            )
            and item.recommendation == "strong-candidate"
        ]
        if len(matches) != 1:
            raise SystemExit(
                "expected exactly one strong candidate; use --candidate-path"
            )
        candidate = matches[0]
        destination = materialize_asset(
            candidate,
            roots=tuple(args.search_root),
            destination_directory=args.destination,
        )
        if args.catalog is not None:
            catalog = ReferenceCatalog(args.catalog)
            catalog.initialize()
            catalog.record_source_asset(
                SourceAssetRecord(
                    citekey=candidate.citekey,
                    sha256=candidate.sha256,
                    byte_size=candidate.byte_size,
                    root_alias="materialized-assets",
                    relative_path=destination.name,
                    rights_status=args.rights_status,
                    asset_status="located-local-copy",
                )
            )
        print(destination)
        return 0
    if args.command == "assets-record-plan":
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        plan = AssetDiscoveryPlan.from_json(
            read_path_text(args.plan, label="asset discovery plan")
        )
        for candidate in plan.candidates:
            if candidate.recommendation != "strong-candidate":
                continue
            catalog.record_source_asset(
                SourceAssetRecord(
                    citekey=candidate.citekey,
                    sha256=candidate.sha256,
                    byte_size=candidate.byte_size,
                    root_alias=candidate.root_alias,
                    relative_path=candidate.relative_path,
                    rights_status=args.rights_status,
                    asset_status=args.asset_status,
                )
            )
        return 0
    if args.command == "acquisition-create":
        stream = io.StringIO(
            read_path_text(args.metadata, label="acquisition metadata"),
            newline="",
        )
        rows = tuple(
            {
                str(key): str(value)
                for key, value in row.items()
                if key is not None and value is not None
            }
            for row in csv.DictReader(stream)
        )
        manifest = create_acquisition_manifest(
            source_id=args.source_id,
            rows=rows,
            roots=tuple(args.source_root),
        )
        try:
            write_path_bytes(
                args.output,
                manifest.to_json().encode("utf-8"),
                label="acquisition manifest",
                replace=False,
            )
        except FileExistsError:
            raise SystemExit(
                f"refusing to overwrite manifest: {args.output}"
            ) from None
        print(f"wrote {len(manifest.entries)} entries to {args.output}")
        return 0
    if args.command == "acquisition-verify":
        manifest = AcquisitionManifest.from_json(
            read_path_text(args.manifest, label="acquisition manifest")
        )
        verify_acquisition_manifest(
            manifest,
            roots=tuple(args.source_root),
        )
        print(
            json.dumps(
                {
                    "schema_version": manifest.schema_version,
                    "source_id": manifest.source_id,
                    "verified": len(manifest.entries),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "enrich-crossref":
        result = CrossrefClient(
            mailto=args.mailto,
            cache_directory=args.cache,
        ).fetch(args.doi)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        imported = load_bibliography(
            args.bibliography,
            source_id=args.source_id,
        )
        issues = validate_reference_objects(
            imported.records,
            notes_directory=args.notes,
            pdf_directory=args.pdfs,
        )
        for issue in issues:
            print(f"{issue.code}: {issue.path}: {issue.message}")
        return 1 if issues else 0
    raise AssertionError(f"unhandled command: {args.command}")
