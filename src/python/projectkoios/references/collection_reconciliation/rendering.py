from __future__ import annotations

import csv
import io
import json

from projectkoios.references.citation_closure import (
    CitationClosure,
)
from projectkoios.references.coverage import (
    CoverageObservation,
)
from projectkoios.references.reconciliation_package import (
    pretty_json,
)

from ._contract import (
    _SCHEMA_VERSION,
)
from .models import (
    CollectionManifest,
    CollectionReference,
    ExtraPdf,
    PdfExpectation,
    PdfStatus,
)


def _render_outputs(
    manifest: CollectionManifest,
    closure: CitationClosure | None,
    coverage_observation: CoverageObservation | None,
) -> dict[str, bytes]:
    missing_rows = [
        record
        for record in manifest.references
        if record.pdf_expectation is PdfExpectation.EXPECTED
        and record.managed_pdf is None
    ]
    ambiguous_rows = [
        record
        for record in manifest.references
        if record.pdf_status is PdfStatus.AMBIGUOUS_MATCHES
    ]
    return {
        "collection-manifest.json": manifest.to_json().encode("utf-8"),
        "reference-state-projections.json": pretty_json(
            {
                "schema_version": 1,
                "artifact_kind": (
                    "projectkoios.references.collection-state-projections"
                ),
                "authoritative_input_ids": sorted(
                    {
                        input_id
                        for projection in manifest.state_projections
                        for input_id in projection.authoritative_input_ids
                    }
                ),
                "projections": [
                    json.loads(item.to_json())
                    for item in manifest.state_projections
                ],
                "exact_replay": True,
            }
        ).encode("utf-8"),
        "citation-closure.json": (
            closure.to_json().encode("utf-8")
            if closure is not None
            else pretty_json(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "status": "not-supplied",
                    "asserted_source_revision": (
                        manifest.asserted_source_revision
                    ),
                }
            ).encode("utf-8")
        ),
        "coverage-observation.json": (
            coverage_observation.to_json().encode("utf-8")
            if coverage_observation is not None
            else pretty_json(
                {
                    "schema_version": 1,
                    "status": "not-supplied",
                    "ambiguity_evaluation": "not-evaluated",
                }
            ).encode("utf-8")
        ),
        "missing-pdfs.csv": _reference_csv(missing_rows).encode("utf-8"),
        "ambiguous-pdfs.csv": _reference_csv(ambiguous_rows).encode("utf-8"),
        "extra-pdfs.csv": _extra_csv(manifest.extra_pdfs).encode("utf-8"),
    }


def _reference_csv(records: list[CollectionReference]) -> str:
    stream = io.StringIO(newline="")
    fields = (
        "proposed_citekey",
        "identity_status",
        "citekey_status",
        "entry_type",
        "source_type",
        "full_text_expected",
        "title",
        "year",
        "doi",
        "source_bibliographies",
        "metadata_verification_status",
        "reading_decision_status",
        "pdf_expectation",
        "pdf_status",
        "acquisition_status",
        "access_status",
        "rights_status",
        "ingestion_status",
        "transcript_status",
        "state_projection_id",
        "state_discrepancy_fields",
        "next_lawful_action",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "proposed_citekey": record.proposed_citekey,
                "identity_status": record.identity_status,
                "citekey_status": record.citekey_status,
                "entry_type": record.entry_type,
                "source_type": record.source_type,
                "full_text_expected": (
                    ""
                    if record.full_text_expected is None
                    else str(record.full_text_expected).lower()
                ),
                "title": record.title or "",
                "year": record.year or "",
                "doi": record.doi or "",
                "source_bibliographies": ";".join(record.source_bibliographies),
                "metadata_verification_status": (
                    record.metadata_verification_status
                ),
                "reading_decision_status": record.reading_decision_status,
                "pdf_expectation": record.pdf_expectation,
                "pdf_status": record.pdf_status,
                "acquisition_status": record.acquisition_status,
                "access_status": record.access_status,
                "rights_status": record.rights_status,
                "ingestion_status": record.ingestion_status,
                "transcript_status": record.transcript_status,
                "state_projection_id": record.state_projection_id,
                "state_discrepancy_fields": ";".join(
                    record.state_discrepancy_fields
                ),
                "next_lawful_action": record.next_lawful_action,
            }
        )
    return stream.getvalue()


def _extra_csv(extras: tuple[ExtraPdf, ...]) -> str:
    stream = io.StringIO(newline="")
    fields = (
        "filename",
        "proposed_citekey",
        "sha256",
        "byte_size",
        "duplicate_citekeys",
        "access_status",
        "rights_status",
        "ingestion_status",
        "transcript_status",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for extra in extras:
        writer.writerow(
            {
                "filename": extra.filename,
                "proposed_citekey": extra.proposed_citekey,
                "sha256": extra.sha256,
                "byte_size": extra.byte_size,
                "duplicate_citekeys": ";".join(extra.duplicate_citekeys),
                "access_status": extra.access_status,
                "rights_status": extra.rights_status,
                "ingestion_status": extra.ingestion_status,
                "transcript_status": extra.transcript_status,
            }
        )
    return stream.getvalue()
