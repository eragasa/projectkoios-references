from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from projectkoios.references import (
    InvalidProvidedReference,
    ProvidedReferenceIntakeError,
    ProvidedReferenceIntakeStore,
    ProvidedReferenceStatus,
)


def test__receive__publishes_immutable_private_pdf_and_deduplicates(
    tmp_path: Path,
) -> None:
    store = ProvidedReferenceIntakeStore(tmp_path / "provided-references")
    pdf = b"%PDF-1.7\nexample\n%%EOF\n"

    first = store.receive(
        claim_id="C-001",
        citation_label="ExampleAuthor2024",
        doi_or_url="10.0000/example",
        note="Supplied for review.",
        pdf_bytes=pdf,
        received_at_utc="2026-09-21T00:00:00+00:00",
    )
    second = store.receive(
        claim_id="C-001",
        citation_label="ExampleAuthor2024",
        doi_or_url="10.0000/example",
        note="Supplied for review.",
        pdf_bytes=pdf,
        received_at_utc="2026-09-22T00:00:00+00:00",
    )

    assert first.receipt_id == second.receipt_id
    assert second.duplicate is True
    assert first.status is ProvidedReferenceStatus.RECEIVED_NOT_INGESTED
    object_path = store.object_path(first.source_sha256)
    assert object_path.read_bytes() == pdf
    assert (object_path.stat().st_mode & 0o777) == 0o600
    assert (object_path.parent.stat().st_mode & 0o777) == 0o700
    records = tuple((tmp_path / "provided-references" / "records").iterdir())
    assert len(records) == 1
    assert (records[0].stat().st_mode & 0o777) == 0o600


def test__record_ingestion__is_separate_and_remains_unreviewed(
    tmp_path: Path,
) -> None:
    store = ProvidedReferenceIntakeStore(tmp_path / "provided-references")
    received = store.receive(
        claim_id="C-001",
        citation_label="ExampleAuthor2024",
        doi_or_url=None,
        note="",
        pdf_bytes=b"%PDF-1.7\nexample\n%%EOF\n",
    )

    ingested = store.record_ingestion(
        receipt_id=received.receipt_id,
        source_id=f"rag:sha256:{received.source_sha256}",
        latest_generation="assessment-v2",
        affected_claims=("C-001",),
        review_boundary="Scientific conclusions remain AUTOMATED_UNREVIEWED.",
        recorded_at_utc="2026-09-21T01:00:00+00:00",
    )

    assert (
        ingested.status is ProvidedReferenceStatus.INGESTED_AUTOMATED_UNREVIEWED
    )
    assert ingested.latest_generation == "assessment-v2"
    assert store.list() == (ingested,)
    with pytest.raises(ProvidedReferenceIntakeError):
        store.record_ingestion(
            receipt_id=received.receipt_id,
            source_id=f"rag:sha256:{received.source_sha256}",
            latest_generation="assessment-v3",
            affected_claims=("C-001",),
            review_boundary="Still unreviewed.",
        )


def test__record_ingestion__rejects_different_source_identity(
    tmp_path: Path,
) -> None:
    store = ProvidedReferenceIntakeStore(tmp_path / "provided-references")
    received = store.receive(
        claim_id="C-001",
        citation_label="ExampleAuthor2024",
        doi_or_url=None,
        note="",
        pdf_bytes=b"%PDF-1.7\nexample\n%%EOF\n",
    )

    with pytest.raises(InvalidProvidedReference):
        store.record_ingestion(
            receipt_id=received.receipt_id,
            source_id="rag:sha256:" + "0" * 64,
            latest_generation="assessment-v2",
            affected_claims=("C-001",),
            review_boundary="Unreviewed.",
        )


def test__object_path__detects_content_corruption(tmp_path: Path) -> None:
    store = ProvidedReferenceIntakeStore(tmp_path / "provided-references")
    pdf = b"%PDF-1.7\nexample\n%%EOF\n"
    received = store.receive(
        claim_id="C-001",
        citation_label="ExampleAuthor2024",
        doi_or_url=None,
        note="",
        pdf_bytes=pdf,
    )
    path = (
        tmp_path
        / "provided-references"
        / "objects"
        / received.source_sha256[:2]
        / f"{received.source_sha256}.pdf"
    )
    path.write_bytes(b"%PDF-corrupt")
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest() != received.source_sha256
    )

    with pytest.raises(ProvidedReferenceIntakeError):
        store.object_path(received.source_sha256)
