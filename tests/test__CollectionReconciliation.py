from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from projectkoios.references.acquisition import (
    ACQUISITION_CONTRACT_ID,
    ACQUISITION_CONTRACT_STATUS,
    ACQUISITION_CONTRACT_VERSION,
    AccessObservation,
    AcquisitionObservation,
    AcquisitionProjection,
    RightsObservation,
)
from projectkoios.references.assets import AssetDiscoveryPlanner, SearchRoot
from projectkoios.references.collection_reconciliation import (
    CitationStatus,
    CollectionReconciliationError,
    CollectionRowEvidence,
    PdfExpectation,
    PdfStatus,
    reconcile_collection,
)
from projectkoios.references.collection_reconciliation import (
    build_citation_closure as _build_citation_closure,
)
from projectkoios.references.collection_reconciliation import (
    load_collection_rows as _load_collection_rows,
)
from projectkoios.references.collection_reconciliation import (
    publish_reconciliation as _publish_reconciliation,
)
from projectkoios.references.collection_reconciliation import (
    scan_managed_pdfs as _scan_managed_pdfs,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)
from projectkoios.references.ingestion_evidence import (
    ReferenceEvidenceInput as _ReferenceEvidenceInput,
)
from projectkoios.references.ingestion_evidence import (
    load_ingestion_reference_evidence,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import RootStorageClass
from projectkoios.references.review import (
    HumanReviewDecision,
    HumanReviewDimension,
    ReadingDecision,
    ReviewActorKind,
    ReviewActorProvenance,
    ReviewAuthorityScope,
    ReviewTransitionKind,
    replay_review_records,
)


def ReferenceEvidenceInput(citekey: str, path: Path) -> _ReferenceEvidenceInput:
    return _ReferenceEvidenceInput(citekey, path, RootStorageClass.LOCAL)


def build_citation_closure(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    return _build_citation_closure(*args, **kwargs)  # type: ignore[arg-type]


def scan_managed_pdfs(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    if kwargs.get("source_discovery") is not None:
        kwargs["source_discovery_storage_class"] = RootStorageClass.LOCAL
    return _scan_managed_pdfs(*args, **kwargs)  # type: ignore[arg-type]


def load_collection_rows(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    return _load_collection_rows(*args, **kwargs)  # type: ignore[arg-type]


def publish_reconciliation(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["output_storage_class"] = RootStorageClass.LOCAL
    return _publish_reconciliation(*args, **kwargs)  # type: ignore[arg-type]


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


def _candidate(**values: object) -> ReferenceCandidate:
    return ReferenceCandidate.create(
        **values,  # type: ignore[arg-type]
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def _records() -> tuple[ReferenceCandidate, ...]:
    return (
        _candidate(
            proposed_citekey="beta2021",
            entry_type="article",
            title="Beta",
            authors=("B. Author",),
            year="2021",
            doi="10.1000/beta",
        ),
        _candidate(
            proposed_citekey="manual2022",
            entry_type="manual",
            title="Manual",
            authors=(),
            year="2022",
        ),
        _candidate(
            proposed_citekey="alpha2020",
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


def _acquisition_projection(
    candidate: ReferenceCandidate,
) -> AcquisitionProjection:
    return AcquisitionProjection(
        contract_id=ACQUISITION_CONTRACT_ID,
        contract_version=ACQUISITION_CONTRACT_VERSION,
        contract_status=ACQUISITION_CONTRACT_STATUS,
        manifest_id="acquisition-manifest:sha256:" + "a" * 64,
        normalized_input_id="acquisition-input:sha256:" + "b" * 64,
        source_id="synthetic-acquisition",
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        manuscript_status="not-assessed",
        source_content_id="blob:sha256:" + "c" * 64,
        source_sha256="c" * 64,
        source_byte_size=321,
        root_alias="synthetic-staging",
        relative_path=f"{candidate.proposed_citekey}.pdf",
        acquisition=AcquisitionObservation(
            "operator-asserted-lawfully-held",
            "operator-assertion",
        ),
        access=AccessObservation(
            "private-local-bytes-observed",
            "operator-assertion",
        ),
        rights=RightsObservation(
            "cc-by-4.0-operator-asserted",
            "operator-assertion",
        ),
        doi=candidate.doi,
        source_url="https://example.test/synthetic.pdf",
        source_version="published-version",
    )


def _review_projection(candidate: ReferenceCandidate):  # type: ignore[no-untyped-def]
    verification = "actor-verification:sha256:" + "d" * 64
    evidence = "review-evidence:sha256:" + "e" * 64
    decision = HumanReviewDecision.create(
        subject_id=candidate.candidate_id,
        context_id="fixture",
        dimension=HumanReviewDimension.READING,
        decision=ReadingDecision.READ,
        producer=ProducerIdentity("synthetic-review-recorder", "1"),
        transition_kind=ReviewTransitionKind.INITIAL,
        actor=ReviewActorProvenance(
            actor_id="synthetic-reader",
            actor_kind=ReviewActorKind.PERSON,
            authority_scope=ReviewAuthorityScope.REFERENCE_READER,
            authority_domain="projectkoios-references",
            verification_record_id=verification,
            verification_method="synthetic repository admission",
        ),
        evidence_ids=tuple(sorted((verification, evidence))),
        rationale="Synthetic actor-provenanced reading decision.",
        decided_at="2026-09-19T00:00:00Z",
    )
    return replay_review_records((), (decision,))


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
    keys = tuple(record.proposed_citekey for record in _records())
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

    records = {
        record.proposed_citekey: record
        for record in outputs.manifest.references
    }
    assert records["alpha2020"].pdf_status is PdfStatus.MANAGED_VERIFIED
    assert records["alpha2020"].duplicate_citekeys == ("extra2023",)
    assert records["alpha2020"].citation_status is CitationStatus.CITED_DEFINED
    assert records["beta2021"].pdf_expectation is PdfExpectation.EXPECTED
    assert records["beta2021"].pdf_status is PdfStatus.NOT_YET_SEARCHED
    assert records["manual2022"].pdf_status is PdfStatus.PDF_NOT_APPLICABLE
    assert records["manual2022"].full_text_expected is False
    assert outputs.manifest.counts == {
        "references": 3,
        "managed_pdfs": 1,
        "missing_expected_pdfs": 1,
        "not_yet_searched": 1,
        "search_incomplete": 0,
        "search_failed": 0,
        "not_located": 0,
        "located_unverified": 0,
        "ambiguous_matches": 0,
        "alternate_version_only": 0,
        "cloud_placeholders": 0,
        "access_controlled": 0,
        "full_text_not_public": 0,
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
    assert (
        b"proposed_citekey,identity_status,citekey_status"
        in files["missing-pdfs.csv"]
    )
    assert (
        b"unaccepted-candidate,proposed-noncanonical"
        in files["missing-pdfs.csv"]
    )
    assert b"beta2021" in files["missing-pdfs.csv"]
    assert b"manual2022" not in files["missing-pdfs.csv"]
    assert b"extra2023" in files["extra-pdfs.csv"]


def test__reconciliation__consumes_authoritative_state_evidence(
    tmp_path: Path,
) -> None:
    corpus, pdfs, discovery, _ = _inputs(tmp_path)
    records = _records()
    beta = next(item for item in records if item.proposed_citekey == "beta2021")
    plan_root = tmp_path / "plan-root"
    plan_root.mkdir()
    (plan_root / "alpha2020.pdf").write_bytes(b"%PDF-1.4\nalpha")
    asset_plan = AssetDiscoveryPlanner().scan(
        records,
        (SearchRoot("plan-root", plan_root, RootStorageClass.LOCAL),),
    )
    catalog_asset = SourceAssetRecord(
        candidate_id=beta.candidate_id,
        proposed_citekey=beta.proposed_citekey,
        identity_status=beta.lifecycle_status,
        citekey_status=beta.citekey_status,
        sha256="c" * 64,
        byte_size=22,
        root_alias="catalog-root",
        relative_path="beta2021.pdf",
        rights_status="cc-by-4.0-operator-asserted",
        asset_status="acquired-via-bounded-download",
    )
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
        citation_closure=None,
        acquisition_evidence={
            beta.proposed_citekey: _acquisition_projection(beta)
        },
        review_projection=_review_projection(beta),
        catalog_assets={beta.proposed_citekey: (catalog_asset,)},
        asset_plan=asset_plan,
    )

    projected = {
        item.proposed_citekey: item for item in outputs.manifest.references
    }["beta2021"]
    assert projected.acquisition_status == "operator-asserted-lawfully-held"
    assert projected.access_status == "private-local-bytes-observed"
    assert projected.rights_status == "cc-by-4.0-operator-asserted"
    assert projected.reading_decision_status == "read"
    assert projected.identity_status == "unaccepted-candidate"
    assert projected.citekey_status == "proposed-noncanonical"
    assert "manuscript_status" not in projected.state_discrepancy_fields

    state = next(
        item
        for item in outputs.manifest.state_projections
        if item.projection_id == projected.state_projection_id
    )
    with pytest.raises(KeyError):
        state.field("manuscript_status")
    with pytest.raises(KeyError):
        state.field("publication_status")
    with pytest.raises(KeyError):
        state.field("contract_status")
    assert _acquisition_projection(beta).manifest_id in (
        state.authoritative_input_ids
    )
    output_files = dict(outputs.files)
    payload = json.loads(output_files["reference-state-projections.json"])
    assert payload["exact_replay"] is True
    assert state.projection_id == payload["projections"][1]["projection_id"]
    evidence_roles = {item.role for item in outputs.package_manifest.inputs}
    assert "catalog-asset-observations" in evidence_roles
    assert "asset-discovery-plan" in evidence_roles


def test__reconcile_collection__marks_unverified_managed_pdf_present(
    tmp_path: Path,
) -> None:
    corpus, pdfs, discovery, pdf_bytes = _inputs(tmp_path)
    del discovery, pdf_bytes

    outputs = reconcile_collection(
        _records(),
        bibliography_bytes=b"fixture bibliography",
        collection_id="fixture",
        source_revision="abc123",
        collection_rows=load_collection_rows(corpus),
        managed_pdfs=scan_managed_pdfs(pdfs),
        citation_closure=None,
    )

    records = {
        record.proposed_citekey: record
        for record in outputs.manifest.references
    }
    assert records["alpha2020"].pdf_status is PdfStatus.MANAGED_PRESENT


def test__reconcile_collection__distinguishes_websites_and_preprints() -> None:
    evidence = CollectionRowEvidence(
        source_bibliographies=("references.bib",),
        bibliographic_status="imported-unverified",
        reading_status="unread-or-unknown",
    )
    records = (
        _candidate(
            proposed_citekey="projectWebsite",
            entry_type="misc",
            title="Project",
            authors=(),
            year=None,
            url="https://example.org/project/",
        ),
        _candidate(
            proposed_citekey="preprint2024",
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
        collection_rows={
            record.proposed_citekey: evidence for record in records
        },
        managed_pdfs=(),
        citation_closure=None,
    )

    reconciled = {
        record.proposed_citekey: record
        for record in outputs.manifest.references
    }
    assert reconciled["projectWebsite"].source_type == "website"
    assert reconciled["projectWebsite"].full_text_expected is False
    assert (
        reconciled["projectWebsite"].pdf_status is PdfStatus.PDF_NOT_APPLICABLE
    )
    assert reconciled["preprint2024"].source_type == "preprint"
    assert reconciled["preprint2024"].full_text_expected is True
    assert reconciled["preprint2024"].pdf_status is PdfStatus.NOT_YET_SEARCHED


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
            bibliography_keys=tuple(
                record.proposed_citekey for record in records
            ),
            source_revision="abc123",
        ),
    )
    destination = tmp_path / "output" / "fixture"

    created = publish_reconciliation(outputs, output_directory=destination)
    unchanged = publish_reconciliation(outputs, output_directory=destination)

    assert created.status == "created"
    assert unchanged.status == "unchanged"
    assert created.package_id == unchanged.package_id
    assert created.package_id == outputs.package_manifest.package_id

    (destination / "missing-pdfs.csv").write_text(
        "different\n",
        encoding="utf-8",
    )
    with pytest.raises(
        CollectionReconciliationError,
        match="differs",
    ):
        publish_reconciliation(outputs, output_directory=destination)


def test__reconcile_collection__uses_injected_source_bound_evidence(
    tmp_path: Path,
) -> None:
    corpus, pdfs, discovery, pdf_bytes = _inputs(tmp_path)
    del discovery
    managed = scan_managed_pdfs(pdfs)
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "ingestion-reference-evidence"
        / "complete.json"
    )
    value = json.loads(fixture.read_bytes())
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    value["source"] = {
        "blob_id": f"blob:sha256:{digest}",
        "hash_algorithm": "sha256",
        "content_sha256": digest,
        "byte_length": len(pdf_bytes),
        "media_type": "application/pdf",
    }
    identity = dict(value)
    identity.pop("record_id")
    record_digest = hashlib.sha256(
        json.dumps(
            [identity],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    value["record_id"] = f"reference-evidence-record:sha256:{record_digest}"
    evidence_path = tmp_path / "alpha-evidence.json"
    evidence_path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    evidence = load_ingestion_reference_evidence(
        (ReferenceEvidenceInput("alpha2020", evidence_path),),
        managed_pdfs=managed,
    )

    outputs = reconcile_collection(
        _records(),
        bibliography_bytes=b"fixture bibliography",
        collection_id="fixture",
        source_revision="abc123",
        collection_rows=load_collection_rows(corpus),
        managed_pdfs=managed,
        citation_closure=None,
        processing_evidence=evidence,
    )
    records = {
        record.proposed_citekey: record
        for record in outputs.manifest.references
    }
    assert records["alpha2020"].ingestion_status == (
        "completed-source-bound-reference-evidence"
    )
    assert records["alpha2020"].transcript_status == (
        "automated-unreviewed-with-recorded-passing-audit"
    )
    assert records["beta2021"].ingestion_status == (
        "reference-evidence-not-supplied"
    )
    assert records["beta2021"].transcript_status == (
        "reference-evidence-not-supplied"
    )
    assert "processing-contract:proposed" in outputs.manifest.coverage
    assert (
        "processing-independent-revalidation:not-performed"
        in outputs.manifest.coverage
    )


def test__scan_managed_pdfs__rejects_non_pdf_bytes(tmp_path: Path) -> None:
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "notPdf.pdf").write_text("not a PDF", encoding="utf-8")

    with pytest.raises(
        CollectionReconciliationError,
        match="lacks PDF header",
    ):
        scan_managed_pdfs(pdfs)
