from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from projectkoios.references.collection_reconciliation import (
    CitationStatus,
    CollectionReconciliationError,
    CollectionRowEvidence,
    PdfExpectation,
    PdfStatus,
    build_citation_closure,
    load_collection_rows,
    publish_reconciliation,
    reconcile_collection,
    scan_managed_pdfs,
    scan_processing_evidence,
)
from projectkoios.references.models import ReferenceRecord


def _write_collection_rows(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "citekey",
                "source_bibliographies",
                "bibliographic_status",
                "reading_status",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for citekey in ("alpha2020", "beta2021", "manual2022"):
            writer.writerow(
                {
                    "citekey": citekey,
                    "source_bibliographies": "manuscript/references.bib",
                    "bibliographic_status": "imported-unverified",
                    "reading_status": "unread-or-unknown",
                }
            )


def _records() -> tuple[ReferenceRecord, ...]:
    return (
        ReferenceRecord(
            citekey="beta2021",
            entry_type="article",
            title="Beta",
            authors=("B. Author",),
            year="2021",
            doi="10.1000/beta",
        ),
        ReferenceRecord(
            citekey="manual2022",
            entry_type="manual",
            title="Manual",
            authors=(),
            year="2022",
        ),
        ReferenceRecord(
            citekey="alpha2020",
            entry_type="article",
            title="Alpha",
            authors=("A. Author",),
            year="2020",
            doi="10.1000/alpha",
        ),
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, bytes]:
    corpus = tmp_path / "corpus.csv"
    _write_collection_rows(corpus)

    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    pdf_bytes = b"%PDF-1.4\nfixture\n%%EOF\n"
    (pdfs / "alpha2020.pdf").write_bytes(pdf_bytes)
    (pdfs / "extra2023.pdf").write_bytes(pdf_bytes)

    discovery = tmp_path / "source-discovery.json"
    discovery.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "matches": [
                    {
                        "citekey": "alpha2020",
                        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                        "match_basis": "fixture identity evidence",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(
        """
        \\cite{alpha2020,beta2021}
        % \\cite{commentedOut}
        Literal percent \\% then \\textcite{undefined2024}.
        \\newcommand{\\wrappedcite}[1]{\\cite{#1}}
        \\newcommand{\\nestedwrappedcite}[1]{\\cite{##1}}
        """,
        encoding="utf-8",
    )
    return corpus, pdfs, discovery, pdf_bytes


def test__build_citation_closure__is_deterministic_and_ignores_comments(
    tmp_path: Path,
) -> None:
    corpus, pdfs, discovery, pdf_bytes = _inputs(tmp_path)
    del corpus, pdfs, discovery, pdf_bytes

    keys = ("alpha2020", "beta2021", "manual2022")
    first = build_citation_closure(
        tmp_path / "manuscript",
        bibliography_keys=keys,
        source_revision="abc123",
    )
    second = build_citation_closure(
        tmp_path / "manuscript",
        bibliography_keys=tuple(reversed(keys)),
        source_revision="abc123",
    )

    assert first == second
    assert first.cited_and_defined == ("alpha2020", "beta2021")
    assert first.cited_but_undefined == ("undefined2024",)
    assert first.defined_but_uncited == ("manual2022",)
    assert "commentedOut" not in first.to_json()
    assert "#1" not in first.to_json()


def test__reconcile_collection__classifies_missing_and_extra_pdfs(
    tmp_path: Path,
) -> None:
    corpus, pdfs, discovery, pdf_bytes = _inputs(tmp_path)
    del pdf_bytes
    keys = tuple(record.citekey for record in _records())
    closure = build_citation_closure(
        tmp_path / "manuscript",
        bibliography_keys=keys,
        source_revision="abc123",
    )

    outputs = reconcile_collection(
        _records(),
        bibliography_bytes=b"fixture bibliography",
        collection_id="fixture",
        source_revision="abc123",
        collection_rows=load_collection_rows(corpus),
        managed_pdfs=scan_managed_pdfs(
            pdfs,
            source_discovery=discovery,
        ),
        citation_closure=closure,
    )

    records = {record.citekey: record for record in outputs.manifest.references}
    assert records["alpha2020"].pdf_status is PdfStatus.MANAGED_VERIFIED
    assert records["alpha2020"].duplicate_citekeys == ("extra2023",)
    assert records["alpha2020"].citation_status is CitationStatus.CITED_DEFINED
    assert records["beta2021"].pdf_expectation is PdfExpectation.EXPECTED
    assert records["beta2021"].pdf_status is PdfStatus.NOT_LOCATED
    assert records["manual2022"].pdf_status is PdfStatus.PDF_NOT_APPLICABLE
    assert records["manual2022"].full_text_expected is False
    assert outputs.manifest.counts == {
        "references": 3,
        "managed_pdfs": 1,
        "missing_expected_pdfs": 1,
        "pdf_applicability_review": 0,
        "pdf_not_applicable": 1,
        "extra_pdfs": 1,
        "seed_raw_extractions": 0,
        "seed_transcripts_with_recorded_passing_audit": 0,
        "extra_raw_extractions": 0,
        "extra_transcripts_with_recorded_passing_audit": 0,
        "duplicate_content_groups": 1,
        "cited_and_defined": 2,
        "cited_but_undefined": 1,
        "defined_but_uncited": 1,
    }
    extra_citekeys = tuple(
        extra.proposed_citekey for extra in outputs.manifest.extra_pdfs
    )
    assert extra_citekeys == ("extra2023",)
    files = dict(outputs.files)
    assert b"beta2021" in files["missing-pdfs.csv"]
    assert b"manual2022" not in files["missing-pdfs.csv"]
    assert b"extra2023" in files["extra-pdfs.csv"]


def test__reconcile_collection__distinguishes_websites_and_preprints() -> None:
    evidence = CollectionRowEvidence(
        source_bibliographies=("references.bib",),
        bibliographic_status="imported-unverified",
        reading_status="unread-or-unknown",
    )
    records = (
        ReferenceRecord(
            citekey="projectWebsite",
            entry_type="misc",
            title="Project",
            authors=(),
            year=None,
            url="https://example.org/project/",
        ),
        ReferenceRecord(
            citekey="preprint2024",
            entry_type="misc",
            title="Preprint",
            authors=(),
            year="2024",
            doi="10.48550/arxiv.2401.00001",
            eprint="2401.00001",
        ),
    )

    outputs = reconcile_collection(
        records,
        bibliography_bytes=b"fixture bibliography",
        collection_id="fixture",
        source_revision="abc123",
        collection_rows={record.citekey: evidence for record in records},
        managed_pdfs=(),
        citation_closure=None,
    )

    reconciled = {
        record.citekey: record for record in outputs.manifest.references
    }
    assert reconciled["projectWebsite"].source_type == "website"
    assert reconciled["projectWebsite"].full_text_expected is False
    assert (
        reconciled["projectWebsite"].pdf_status is PdfStatus.PDF_NOT_APPLICABLE
    )
    assert reconciled["preprint2024"].source_type == "preprint"
    assert reconciled["preprint2024"].full_text_expected is True
    assert reconciled["preprint2024"].pdf_status is PdfStatus.NOT_LOCATED


def test__publish_reconciliation__is_immutable_and_replayable(
    tmp_path: Path,
) -> None:
    corpus, pdfs, discovery, pdf_bytes = _inputs(tmp_path)
    del pdf_bytes
    records = _records()
    outputs = reconcile_collection(
        records,
        bibliography_bytes=b"fixture bibliography",
        collection_id="fixture",
        source_revision="abc123",
        collection_rows=load_collection_rows(corpus),
        managed_pdfs=scan_managed_pdfs(
            pdfs,
            source_discovery=discovery,
        ),
        citation_closure=build_citation_closure(
            tmp_path / "manuscript",
            bibliography_keys=tuple(record.citekey for record in records),
            source_revision="abc123",
        ),
    )
    destination = tmp_path / "output" / "fixture"

    created = publish_reconciliation(outputs, output_directory=destination)
    unchanged = publish_reconciliation(outputs, output_directory=destination)

    assert created.status == "created"
    assert unchanged.status == "unchanged"
    assert created.manifest_id == unchanged.manifest_id

    (destination / "missing-pdfs.csv").write_text(
        "different\n",
        encoding="utf-8",
    )
    with pytest.raises(
        CollectionReconciliationError,
        match="differs",
    ):
        publish_reconciliation(outputs, output_directory=destination)


def test__scan_processing_evidence__classifies_audited_transcript(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ingestion"
    transcript = root / "alpha2020" / "derived" / "transcription"
    transcript.mkdir(parents=True)
    (root / "alpha2020" / "extraction.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (transcript / "manifest.json").write_text(
        '{"status":"automated_unreviewed"}\n',
        encoding="utf-8",
    )
    (transcript / "audit.json").write_text(
        '{"status":"passed"}\n',
        encoding="utf-8",
    )
    (transcript / "clean.json").write_text("{}\n", encoding="utf-8")
    (transcript / "clean.txt").write_text("evidence\n", encoding="utf-8")

    evidence = scan_processing_evidence(
        root,
        citekeys=("beta2021", "alpha2020"),
    )

    assert evidence["alpha2020"].ingestion_status == "raw-extraction-present"
    assert (
        evidence["alpha2020"].transcript_status
        == "automated-unreviewed-with-recorded-passing-audit"
    )
    assert evidence["beta2021"].ingestion_status == "not-ingested"
    assert evidence["beta2021"].transcript_status == "not-transcribed"


def test__scan_managed_pdfs__rejects_non_pdf_bytes(tmp_path: Path) -> None:
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "notPdf.pdf").write_text("not a PDF", encoding="utf-8")

    with pytest.raises(
        CollectionReconciliationError,
        match="lacks PDF header",
    ):
        scan_managed_pdfs(pdfs)
