from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from projectkoios.references.cli import main
from projectkoios.references.collection_reconciliation import (
    ManagedPdf,
    ProcessingEvidence,
)
from projectkoios.references.ingestion_evidence import (
    REFERENCE_EVIDENCE_CONTRACT_STATUS,
    REFERENCE_EVIDENCE_MAX_BYTES,
    IngestionEvidenceLimitError,
    IngestionEvidenceParseError,
    IngestionEvidenceVerificationError,
    ReferenceEvidenceInput,
    load_ingestion_reference_evidence,
    parse_reference_evidence,
    verify_reference_evidence_source,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "ingestion-reference-evidence"
_SOURCE_BYTES = b"sanitized reference-evidence fixture source\n"
_COMPLETE_SHA256 = (
    "56b5d0aff7f692b27700786b8828a86240be1ecb647bac7d64ad4a152d0de405"
)
_UNSUPPORTED_SHA256 = (
    "7ed795c742d9237434230c46b1a4e59c3ba364ce92dbf9b4f39d0b0df4f293da"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reidentify(value: dict[str, object]) -> bytes:
    body = deepcopy(value)
    body.pop("record_id", None)
    digest = hashlib.sha256(_canonical([body])).hexdigest()
    value["record_id"] = f"reference-evidence-record:sha256:{digest}"
    return _canonical(value)


def _evidence_for_source(content: bytes) -> bytes:
    value = json.loads((_FIXTURES / "complete.json").read_bytes())
    digest = hashlib.sha256(content).hexdigest()
    value["source"] = {
        "blob_id": f"blob:sha256:{digest}",
        "hash_algorithm": "sha256",
        "content_sha256": digest,
        "byte_length": len(content),
        "media_type": "application/pdf",
    }
    return _reidentify(value)


def _managed(citekey: str, content: bytes) -> ManagedPdf:
    return ManagedPdf(
        filename=f"{citekey}.pdf",
        citekey=citekey,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        historically_verified=False,
        discovery_evidence=(),
    )


def test__processing_evidence__cannot_be_constructed_without_adapter() -> None:
    with pytest.raises(TypeError):
        ProcessingEvidence(  # type: ignore[call-arg]
            ingestion_status="completed-source-bound-reference-evidence",
            transcript_status=(
                "automated-unreviewed-with-recorded-passing-audit"
            ),
            evidence_record_id="reference-evidence-record:sha256:" + "0" * 64,
            contract_status="proposed",
            derivation_audit_status="recorded-passing",
            derivation_audit_scope="recorded_producer_derivation_audit",
            independently_revalidated=False,
        )


def test__ingestion_reference_evidence__producer_fixtures_are_exact() -> None:
    complete = (_FIXTURES / "complete.json").read_bytes()
    unsupported = (_FIXTURES / "unsupported-generation.json").read_bytes()

    assert len(complete) == 3685
    assert hashlib.sha256(complete).hexdigest() == _COMPLETE_SHA256
    assert len(unsupported) == 3686
    assert hashlib.sha256(unsupported).hexdigest() == _UNSUPPORTED_SHA256
    record = parse_reference_evidence(complete)
    assert record.to_bytes() == complete
    assert record.record_id == (
        "reference-evidence-record:sha256:"
        "4e4ff0df36dcaace4d169050407d3f4eba64c9cdb8a47f12a30ff01ffd1d33c6"
    )
    assert record.contract_status == REFERENCE_EVIDENCE_CONTRACT_STATUS
    assert record.derivation_audit.status == "passed"
    assert record.derivation_audit.scope == (
        "recorded_producer_derivation_audit"
    )
    assert record.derivation_audit.independently_revalidated is False
    verify_reference_evidence_source(
        record,
        source_sha256=hashlib.sha256(_SOURCE_BYTES).hexdigest(),
        source_byte_length=len(_SOURCE_BYTES),
    )


def test__ingestion_reference_evidence__unsupported_fixture_fails() -> None:
    with pytest.raises(
        IngestionEvidenceParseError,
        match="unsupported transcript artifact generation",
    ):
        parse_reference_evidence(
            (_FIXTURES / "unsupported-generation.json").read_bytes()
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown-field", "unknown fields"),
        ("contract-version", "unsupported reference-evidence contract version"),
        ("schema-version", "unsupported reference-evidence schema version"),
        (
            "generator-name",
            "unsupported reference-evidence generator name",
        ),
        (
            "generator-version",
            "unsupported reference-evidence generator version",
        ),
        ("transcript-generation", "unsupported transcript artifact generation"),
        ("extraction-status", "requires completed extraction"),
        ("transcript-status", "requires automated-unreviewed"),
        ("source-media", "unsupported source media type"),
        ("missing-lineage", "derivation-audit lineage is incomplete"),
        ("audit-coverage", "layer coverage is incomplete"),
        ("audit-status", "requires a recorded passing audit"),
        ("independent-claim", "cannot claim independent revalidation"),
        ("incomplete", "not complete"),
    ),
)
def test__ingestion_reference_evidence__semantic_tampering_fails(
    mutation: str,
    message: str,
) -> None:
    value = json.loads((_FIXTURES / "complete.json").read_bytes())
    if mutation == "unknown-field":
        value["unknown"] = True
    elif mutation == "contract-version":
        value["contract_version"] = "0.2.0"
    elif mutation == "schema-version":
        value["schema_version"] = 2
    elif mutation == "generator-name":
        value["generator_name"] = "unknown-generator"
    elif mutation == "generator-version":
        value["generator_version"] = "2"
    elif mutation == "transcript-generation":
        value["transcript"]["artifact_generation"] = 2
    elif mutation == "extraction-status":
        value["extraction"]["status"] = "partial"
    elif mutation == "transcript-status":
        value["transcript"]["status"] = "human-reviewed"
    elif mutation == "source-media":
        value["source"]["media_type"] = "application/octet-stream"
    elif mutation == "missing-lineage":
        value["derivation_audit"]["audited_artifact_ids"].pop()
    elif mutation == "audit-coverage":
        value["derivation_audit"]["audited_layer_counts"][0]["count"] = 0
    elif mutation == "audit-status":
        value["derivation_audit"]["status"] = "failed"
    elif mutation == "independent-claim":
        value["derivation_audit"]["independently_revalidated"] = True
    else:
        value["completeness"] = "incomplete"
        value["completeness_reasons"] = ["fixture-partial"]

    with pytest.raises(
        (IngestionEvidenceParseError, IngestionEvidenceVerificationError),
        match=message,
    ):
        parse_reference_evidence(_reidentify(value))


def test__ingestion_reference_evidence__identity_and_canonical_failures() -> (
    None
):
    content = (_FIXTURES / "complete.json").read_bytes()
    value = json.loads(content)
    value["record_id"] = "reference-evidence-record:sha256:" + "0" * 64
    with pytest.raises(IngestionEvidenceParseError, match="record ID"):
        parse_reference_evidence(_canonical(value))

    with pytest.raises(IngestionEvidenceParseError, match="not canonical"):
        parse_reference_evidence(content + b"\n")

    duplicate = content[:-1] + b',"schema_version":1}'
    with pytest.raises(IngestionEvidenceParseError, match="duplicate JSON"):
        parse_reference_evidence(duplicate)


def test__ingestion_reference_evidence__rejects_oversize_and_partial() -> None:
    with pytest.raises(IngestionEvidenceLimitError, match="size limit"):
        parse_reference_evidence(b" " * (REFERENCE_EVIDENCE_MAX_BYTES + 1))

    value = json.loads((_FIXTURES / "complete.json").read_bytes())
    del value["derivation_audit"]
    with pytest.raises(IngestionEvidenceParseError, match="missing fields"):
        parse_reference_evidence(_canonical(value))


def test__ingestion_reference_evidence__loader_binds_exact_managed_pdf(
    tmp_path: Path,
) -> None:
    pdf = b"%PDF-1.4\nconsumer fixture\n%%EOF\n"
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_bytes(_evidence_for_source(pdf))
    binding = ReferenceEvidenceInput("example2026", evidence_path)
    managed = (_managed("example2026", pdf),)

    first = load_ingestion_reference_evidence((binding,), managed_pdfs=managed)
    second = load_ingestion_reference_evidence((binding,), managed_pdfs=managed)

    assert first == second
    observed = first["example2026"]
    assert observed.ingestion_status == (
        "completed-source-bound-reference-evidence"
    )
    assert observed.transcript_status == (
        "automated-unreviewed-with-recorded-passing-audit"
    )
    assert observed.contract_status == "proposed"
    assert observed.derivation_audit_status == "recorded-passing"
    assert observed.derivation_audit_scope == (
        "recorded_producer_derivation_audit"
    )
    assert observed.independently_revalidated is False
    assert {item.role for item in first.input_evidence} == {
        "ingestion-reference-evidence",
        "processing-observation",
    }
    assert str(tmp_path) not in str(first.input_evidence)


def test__collection_reconcile_cli__uses_explicit_evidence_binding(
    tmp_path: Path,
) -> None:
    bibliography = tmp_path / "references.bib"
    bibliography.write_text(
        "@article{example2026, title={Example}, year={2026}}\n",
        encoding="utf-8",
    )
    corpus = tmp_path / "corpus.csv"
    with corpus.open("w", encoding="utf-8", newline="") as stream:
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
        writer.writerow(
            {
                "citekey": "example2026",
                "source_bibliographies": "references.bib",
                "bibliographic_status": "imported-unverified",
                "reading_status": "unread-or-unknown",
            }
        )
    pdf_content = b"%PDF-1.4\nCLI evidence fixture\n%%EOF\n"
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "example2026.pdf").write_bytes(pdf_content)
    evidence = tmp_path / "explicit-evidence.json"
    evidence.write_bytes(_evidence_for_source(pdf_content))
    output = tmp_path / "output"

    assert (
        main(
            [
                "collection-reconcile",
                str(bibliography),
                str(corpus),
                str(pdfs),
                str(output),
                "--collection-id",
                "fixture",
                "--source-revision",
                "asserted-revision",
                "--reference-evidence",
                f"example2026={evidence}",
            ]
        )
        == 0
    )
    manifest = json.loads(
        (output / "collection-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["references"][0]["ingestion_status"] == (
        "completed-source-bound-reference-evidence"
    )
    assert manifest["references"][0]["transcript_status"] == (
        "automated-unreviewed-with-recorded-passing-audit"
    )
    package = json.loads(
        (output / "package-manifest.json").read_text(encoding="utf-8")
    )
    assert "ingestion-reference-evidence" in {
        item["role"] for item in package["inputs"]
    }
    assert str(tmp_path) not in json.dumps(package)


@pytest.mark.parametrize("mismatch", ("sha256", "byte-length", "media-type"))
def test__ingestion_reference_evidence__source_mismatch_fails(
    mismatch: str,
) -> None:
    record = parse_reference_evidence(
        (_FIXTURES / "complete.json").read_bytes()
    )
    values = {
        "source_sha256": hashlib.sha256(_SOURCE_BYTES).hexdigest(),
        "source_byte_length": len(_SOURCE_BYTES),
        "source_media_type": "application/pdf",
    }
    if mismatch == "sha256":
        values["source_sha256"] = "0" * 64
    elif mismatch == "byte-length":
        values["source_byte_length"] = len(_SOURCE_BYTES) + 1
    else:
        values["source_media_type"] = "application/octet-stream"

    with pytest.raises(
        IngestionEvidenceVerificationError,
        match="managed PDF identity",
    ):
        verify_reference_evidence_source(record, **values)  # type: ignore[arg-type]


def test__ingestion_reference_evidence__duplicates_and_missing_pdf_fail(
    tmp_path: Path,
) -> None:
    pdf = b"%PDF-1.4\nduplicate fixture\n%%EOF\n"
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(_evidence_for_source(pdf))
    first = ReferenceEvidenceInput("first2026", evidence)
    second = ReferenceEvidenceInput("second2026", evidence)

    with pytest.raises(
        IngestionEvidenceVerificationError,
        match="duplicate reference-evidence citekey",
    ):
        load_ingestion_reference_evidence(
            (first, first), managed_pdfs=(_managed("first2026", pdf),)
        )

    with pytest.raises(
        IngestionEvidenceVerificationError,
        match="duplicate reference-evidence record",
    ):
        load_ingestion_reference_evidence(
            (first, second),
            managed_pdfs=(
                _managed("first2026", pdf),
                _managed("second2026", pdf),
            ),
        )

    with pytest.raises(
        IngestionEvidenceVerificationError,
        match="no matching managed PDF",
    ):
        load_ingestion_reference_evidence((first,), managed_pdfs=())
