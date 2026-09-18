from __future__ import annotations

import json
from pathlib import Path

import pytest
from projectkoios.references import (
    AmbiguityEvaluation,
    CandidateVersionRelation,
    CoverageAccessState,
    CoverageCandidate,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.cli import main
from projectkoios.references.collection_reconciliation import (
    CollectionReconciliationError,
    CollectionRowEvidence,
    PdfStatus,
    reconcile_collection,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)

_CITEKEY = "example2026"
_REVISION = "asserted-revision"


def _record(*, entry_type: str = "article") -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey=_CITEKEY,
        entry_type=entry_type,
        title="Example",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def _row() -> CollectionRowEvidence:
    return CollectionRowEvidence(
        source_bibliographies=("references.bib",),
        bibliographic_status="imported-unverified",
        reading_status="unread-or-unknown",
    )


def _candidate(
    digit: str,
    *,
    relation: CandidateVersionRelation = (
        CandidateVersionRelation.PRIMARY_OR_UNKNOWN
    ),
    relative_path: str | None = None,
    byte_size: int = 100,
) -> CoverageCandidate:
    return CoverageCandidate(
        root_alias="papers",
        relative_path=(relative_path or f"collection/example-{digit}.pdf"),
        sha256=digit * 64,
        byte_size=byte_size,
        version_relation=relation,
    )


def _result(
    *,
    no_match: bool = False,
    access_state: CoverageAccessState = CoverageAccessState.NONE,
    candidates: tuple[CoverageCandidate, ...] = (),
) -> ReferenceCoverage:
    return ReferenceCoverage(
        citekey=_CITEKEY,
        no_match=no_match,
        access_state=access_state,
        candidates=candidates,
        evidence=("fixture-observation",),
    )


def _observation(
    *,
    state: CoverageState,
    result: ReferenceCoverage | None,
    ambiguity: AmbiguityEvaluation = AmbiguityEvaluation.NOT_EVALUATED,
) -> CoverageObservation:
    return CoverageObservation.create(
        asserted_source_revision=_REVISION,
        state=state,
        authorized_root_aliases=(
            () if state is CoverageState.NOT_STARTED else ("papers",)
        ),
        exclusions=(
            ("bounded-root-not-completed",)
            if state is CoverageState.INCOMPLETE
            else ()
        ),
        failures=(
            ("bounded-search-failed",) if state is CoverageState.FAILED else ()
        ),
        ambiguity_evaluation=ambiguity,
        references=(() if result is None else (result,)),
    )


def _reconcile(
    coverage: CoverageObservation | None,
    *,
    entry_type: str = "article",
):
    record = _record(entry_type=entry_type)
    return reconcile_collection(
        (record,),
        bibliography_bytes=b"fixture",
        collection_id="fixture",
        source_revision=_REVISION,
        collection_rows={record.proposed_citekey: _row()},
        managed_pdfs=(),
        citation_closure=None,
        coverage_observation=coverage,
    )


@pytest.mark.parametrize(
    ("coverage", "expected"),
    (
        (None, PdfStatus.NOT_YET_SEARCHED),
        (
            _observation(
                state=CoverageState.NOT_STARTED,
                result=None,
            ),
            PdfStatus.NOT_YET_SEARCHED,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(no_match=True),
            ),
            PdfStatus.SEARCH_INCOMPLETE,
        ),
        (
            _observation(
                state=CoverageState.FAILED,
                result=_result(no_match=True),
            ),
            PdfStatus.SEARCH_FAILED,
        ),
        (
            _observation(
                state=CoverageState.COMPLETE,
                result=_result(no_match=True),
            ),
            PdfStatus.NOT_LOCATED,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(candidates=(_candidate("1"),)),
            ),
            PdfStatus.LOCATED_UNVERIFIED,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(candidates=(_candidate("1"), _candidate("2"))),
                ambiguity=AmbiguityEvaluation.EVALUATED,
            ),
            PdfStatus.AMBIGUOUS_MATCHES,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(
                    candidates=(
                        _candidate(
                            "1",
                            relation=CandidateVersionRelation.ALTERNATE,
                        ),
                    )
                ),
            ),
            PdfStatus.ALTERNATE_VERSION_ONLY,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(
                    access_state=CoverageAccessState.CLOUD_PLACEHOLDER
                ),
            ),
            PdfStatus.CLOUD_PLACEHOLDER,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(
                    access_state=CoverageAccessState.ACCESS_CONTROLLED
                ),
            ),
            PdfStatus.ACCESS_CONTROLLED,
        ),
        (
            _observation(
                state=CoverageState.INCOMPLETE,
                result=_result(
                    access_state=CoverageAccessState.FULL_TEXT_NOT_PUBLIC
                ),
            ),
            PdfStatus.FULL_TEXT_NOT_PUBLIC,
        ),
    ),
)
def test__coverage_observation__drives_evidence_bearing_statuses(
    coverage: CoverageObservation | None,
    expected: PdfStatus,
) -> None:
    outputs = _reconcile(coverage)
    reference = outputs.manifest.references[0]

    assert reference.pdf_status is expected
    if coverage is None:
        assert outputs.manifest.coverage_observation_id is None
    else:
        assert outputs.manifest.coverage_observation_id == coverage.coverage_id
        assert (
            json.loads(dict(outputs.files)["coverage-observation.json"])[
                "coverage_id"
            ]
            == coverage.coverage_id
        )


def test__coverage_observation__records_actual_ambiguity() -> None:
    coverage = _observation(
        state=CoverageState.INCOMPLETE,
        result=_result(candidates=(_candidate("1"), _candidate("2"))),
        ambiguity=AmbiguityEvaluation.EVALUATED,
    )

    outputs = _reconcile(coverage)

    assert (
        outputs.manifest.ambiguity_evaluation is AmbiguityEvaluation.EVALUATED
    )
    assert b"example2026" in dict(outputs.files)["ambiguous-pdfs.csv"]
    assert outputs.manifest.counts["ambiguous_matches"] == 1


def test__coverage_observation__round_trips_and_is_content_identified() -> None:
    first = _observation(
        state=CoverageState.COMPLETE,
        result=_result(no_match=True),
        ambiguity=AmbiguityEvaluation.EVALUATED,
    )
    restored = CoverageObservation.from_json(first.to_json())
    changed = CoverageObservation.create(
        asserted_source_revision=_REVISION,
        state=CoverageState.COMPLETE,
        authorized_root_aliases=("papers",),
        exclusions=("excluded-private-area",),
        failures=(),
        ambiguity_evaluation=AmbiguityEvaluation.EVALUATED,
        references=(_result(no_match=True),),
    )

    assert restored == first
    assert restored.coverage_id == first.coverage_id
    assert changed.coverage_id != first.coverage_id


def test__coverage_observation__rejects_contradictions() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _result(no_match=True, candidates=(_candidate("1"),))

    with pytest.raises(ValueError, match="evaluated ambiguity"):
        _observation(
            state=CoverageState.INCOMPLETE,
            result=_result(candidates=(_candidate("1"), _candidate("2"))),
        )

    with pytest.raises(
        ValueError,
        match="candidate location has contradictory content identities",
    ):
        _result(
            candidates=(
                _candidate("1", relative_path="collection/same.pdf"),
                _candidate("2", relative_path="collection/same.pdf"),
            )
        )

    with pytest.raises(
        ValueError,
        match="candidate digest has contradictory byte sizes",
    ):
        _result(
            candidates=(
                _candidate(
                    "1",
                    relative_path="collection/first.pdf",
                    byte_size=100,
                ),
                _candidate(
                    "1",
                    relative_path="collection/second.pdf",
                    byte_size=101,
                ),
            )
        )

    unauthorized = ReferenceCoverage(
        citekey=_CITEKEY,
        no_match=False,
        access_state=CoverageAccessState.NONE,
        candidates=(
            CoverageCandidate(
                root_alias="other",
                relative_path="example.pdf",
                sha256="1" * 64,
                byte_size=100,
                version_relation=(CandidateVersionRelation.PRIMARY_OR_UNKNOWN),
            ),
        ),
        evidence=("fixture-observation",),
    )
    with pytest.raises(ValueError, match="unauthorized root"):
        CoverageObservation.create(
            asserted_source_revision=_REVISION,
            state=CoverageState.INCOMPLETE,
            authorized_root_aliases=("papers",),
            exclusions=("bounded-root-not-completed",),
            failures=(),
            ambiguity_evaluation=AmbiguityEvaluation.EVALUATED,
            references=(unauthorized,),
        )


def test__coverage_observation__rejects_tampering_and_source_mismatch() -> None:
    coverage = _observation(
        state=CoverageState.COMPLETE,
        result=_result(no_match=True),
    )
    data = json.loads(coverage.to_json())
    data["state"] = "incomplete"
    data["exclusions"] = ["tampered"]
    with pytest.raises(ValueError, match="identity"):
        CoverageObservation.from_json(json.dumps(data))

    mismatched = CoverageObservation.create(
        asserted_source_revision="different",
        state=CoverageState.COMPLETE,
        authorized_root_aliases=("papers",),
        exclusions=(),
        failures=(),
        ambiguity_evaluation=AmbiguityEvaluation.NOT_EVALUATED,
        references=(_result(no_match=True),),
    )
    with pytest.raises(CollectionReconciliationError, match="source assertion"):
        _reconcile(mismatched)


def test__complete_coverage__must_cover_the_bibliography() -> None:
    incomplete_claim = _observation(
        state=CoverageState.COMPLETE,
        result=None,
    )

    with pytest.raises(CollectionReconciliationError, match="omits"):
        _reconcile(incomplete_claim)


def test__collection_reconcile_cli__consumes_coverage_observation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bibliography = tmp_path / "references.bib"
    bibliography.write_text(
        "@article{example2026, title={Example}, year={2026}}\n",
        encoding="utf-8",
    )
    corpus = tmp_path / "corpus.csv"
    corpus.write_text(
        "citekey,source_bibliographies,bibliographic_status,reading_status\n"
        "example2026,references.bib,imported-unverified,unread-or-unknown\n",
        encoding="utf-8",
    )
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    coverage = _observation(
        state=CoverageState.COMPLETE,
        result=_result(no_match=True),
    )
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(coverage.to_json(), encoding="utf-8")
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
                _REVISION,
                "--coverage-observation",
                str(coverage_path),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    manifest = json.loads((output / "collection-manifest.json").read_text())
    assert report["status"] == "created"
    assert manifest["counts"]["not_located"] == 1
    assert manifest["coverage_observation_id"] == coverage.coverage_id


def test__candidate_for_non_pdf_source__requires_applicability_review() -> None:
    coverage = _observation(
        state=CoverageState.COMPLETE,
        result=_result(candidates=(_candidate("1"),)),
    )

    output = _reconcile(coverage, entry_type="manual")

    assert (
        output.manifest.references[0].pdf_status
        is PdfStatus.PDF_APPLICABILITY_REVIEW
    )
