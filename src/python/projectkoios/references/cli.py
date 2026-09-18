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
from projectkoios.references.ingestion_evidence import (
    ReferenceEvidenceInput,
    load_ingestion_reference_evidence,
)
from projectkoios.references.io_limits import (
    ACQUISITION_IO_LIMITS,
    ASSET_DISCOVERY_IO_LIMITS,
    RECONCILIATION_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_csv_field_size,
    bounded_utf8_size,
)
from projectkoios.references.models import (
    ReviewMembership,
    ReviewStatus,
    SourceAssetRecord,
)
from projectkoios.references.path_safety import (
    PathLimitError,
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


def _reference_evidence(value: str) -> ReferenceEvidenceInput:
    citekey, separator, raw_path = value.partition("=")
    if not separator or not citekey or not raw_path:
        raise argparse.ArgumentTypeError(
            "reference evidence must be CITEKEY=PATH"
        )
    try:
        return ReferenceEvidenceInput(citekey, Path(raw_path).expanduser())
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="koios-ref")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("catalog-init")
    initialize.add_argument("catalog", type=Path)

    import_bib = commands.add_parser(
        "bib-import",
        help="observe BibTeX and import noncanonical candidates",
    )
    import_bib.add_argument("catalog", type=Path)
    import_bib.add_argument("bibliography", type=Path)
    import_bib.add_argument("--source-id", required=True)
    import_bib.add_argument("--source-revision")
    import_bib.add_argument("--source-path")

    import_graph = commands.add_parser("graph-import")
    import_graph.add_argument("catalog", type=Path)
    import_graph.add_argument("sources", type=Path)
    import_graph.add_argument("nodes", type=Path)
    import_graph.add_argument("edges", type=Path)

    summary = commands.add_parser("catalog-summary")
    summary.add_argument("catalog", type=Path)

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
    reconcile.add_argument("--manuscript-root", type=Path)
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
        imported = load_bibliography(
            args.bibliography,
            source_id=args.source_id,
            source_revision=args.source_revision,
            source_path=args.source_path,
        )
        catalog = ReferenceCatalog(args.catalog)
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
        graph = load_candidate_graph(args.sources, args.nodes, args.edges)
        catalog = ReferenceCatalog(args.catalog)
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
        print(json.dumps(ReferenceCatalog(args.catalog).counts(), indent=2))
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
        rows = _bounded_csv_rows(
            args.corpus,
            label="review corpus",
            limits=RECONCILIATION_IO_LIMITS,
        )
        memberships: list[ReviewMembership] = []
        for row in rows:
            citekey = row.get("citekey")
            if not citekey:
                raise ValueError(
                    "review corpus must contain non-empty citekeys"
                )
            memberships.append(
                ReviewMembership(
                    collection_id=args.collection_id,
                    citekey=citekey,
                    status=ReviewStatus(args.status),
                )
            )
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        catalog.set_review_memberships(tuple(memberships))
        return 0
    if args.command == "collection-reconcile":
        imported = load_bibliography(
            args.bibliography,
            source_id=args.collection_id,
            source_revision=args.source_revision,
        )
        bibliography_bytes = imported.bibliography_bytes
        citation_closure = (
            build_citation_closure(
                args.manuscript_root,
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
            source_discovery=args.source_discovery,
        )
        processing_evidence = (
            load_ingestion_reference_evidence(
                tuple(args.reference_evidence),
                managed_pdfs=managed_pdfs,
            )
            if args.reference_evidence
            else None
        )
        coverage_observation_bytes = (
            read_path_bytes(
                args.coverage_observation,
                label="coverage observation",
                max_bytes=_required_limit(
                    RECONCILIATION_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
            if args.coverage_observation is not None
            else None
        )
        coverage_observation = (
            CoverageObservation.from_json(
                coverage_observation_bytes.decode("utf-8")
            )
            if coverage_observation_bytes is not None
            else None
        )
        outputs = reconcile_collection(
            imported.candidates,
            bibliography_bytes=bibliography_bytes,
            collection_id=args.collection_id,
            source_revision=args.source_revision,
            collection_rows=load_collection_rows(args.corpus),
            managed_pdfs=managed_pdfs,
            citation_closure=citation_closure,
            coverage_observation=coverage_observation,
            coverage_observation_bytes=coverage_observation_bytes,
            processing_evidence=processing_evidence,
            bibliography_parser=biblatex_parser_identity(),
        )
        publication = publish_reconciliation(
            outputs,
            output_directory=args.output,
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
        )
        plan = AssetDiscoveryPlanner().scan(
            imported.candidates,
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
            read_path_text(
                args.plan,
                label="asset discovery plan",
                max_bytes=_required_limit(
                    ASSET_DISCOVERY_IO_LIMITS.max_json_bytes,
                    "max_json_bytes",
                ),
            )
        )
        matches = [
            item
            for item in plan.candidates
            if item.proposed_citekey == args.citekey
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
                    candidate_id=candidate.candidate_id,
                    proposed_citekey=candidate.proposed_citekey,
                    identity_status=candidate.identity_status,
                    citekey_status=candidate.citekey_status,
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
        plan = AssetDiscoveryPlan.from_json(
            read_path_text(
                args.plan,
                label="asset discovery plan",
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
                asset_status=args.asset_status,
            )
            for candidate in plan.candidates
            if candidate.recommendation == "strong-candidate"
        )
        catalog = ReferenceCatalog(args.catalog)
        catalog.initialize()
        catalog.record_source_assets(assets)
        return 0
    if args.command == "acquisition-create":
        rows = _bounded_csv_rows(
            args.metadata,
            label="acquisition metadata",
            limits=ACQUISITION_IO_LIMITS,
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
            read_path_text(
                args.manifest,
                label="acquisition manifest",
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
                    "source_id": manifest.source_id,
                    "verified": len(manifest.entries),
                    "coverage_status": "complete",
                    "effective_limits": ACQUISITION_IO_LIMITS.to_dict(),
                    "effective_limits_id": (ACQUISITION_IO_LIMITS.evidence_id),
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
            imported.candidates,
            notes_directory=args.notes,
            pdf_directory=args.pdfs,
        )
        for issue in issues:
            print(f"{issue.code}: {issue.path}: {issue.message}")
        return 1 if issues else 0
    raise AssertionError(f"unhandled command: {args.command}")


def _bounded_csv_rows(
    path: Path,
    *,
    label: str,
    limits: ReferenceIOLimits,
) -> tuple[dict[str, str], ...]:
    max_csv_bytes = _required_limit(limits.max_csv_bytes, "max_csv_bytes")
    try:
        text = read_path_text(
            path,
            label=label,
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
            for row_number, row in enumerate(reader, start=1):
                if row_number > max_rows:
                    raise ReferenceIOLimitError(
                        resource=label,
                        limit_name="max_rows",
                        limit=max_rows,
                        observed=row_number,
                        limits=limits,
                    )
                normalized = {
                    str(key): str(value)
                    for key, value in row.items()
                    if key is not None and value is not None
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
