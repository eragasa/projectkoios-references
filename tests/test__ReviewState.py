from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import projectkoios.references as public_api
import pytest
from projectkoios.references.catalog import (
    CatalogConflictError,
    CatalogSchemaError,
    ReferenceCatalog,
)
from projectkoios.references.identity import ProducerIdentity
from projectkoios.references.io_limits import (
    REVIEW_IO_LIMITS,
    ReferenceIOLimitError,
)
from projectkoios.references.path_safety import RootStorageClass
from projectkoios.references.review import (
    ClaimSupportCheckDecision,
    HumanReviewDecision,
    HumanReviewDimension,
    ReadingDecision,
    ReviewActorKind,
    ReviewActorProvenance,
    ReviewAuthorityScope,
    ReviewInclusionDecision,
    ReviewProjection,
    ReviewRecordError,
    ReviewTransitionKind,
    TechnicalReviewKind,
    TechnicalReviewOutcome,
    TechnicalReviewRecord,
    replay_review_records,
)

_SUBJECT = "reference-candidate:sha256:" + "a" * 64
_ACTOR_EVIDENCE = "actor-verification:sha256:" + "b" * 64
_SOURCE_EVIDENCE = "source-evidence:sha256:" + "c" * 64
_CLAIM = "scientific-claim:sha256:" + "d" * 64
_EVIDENCE = tuple(sorted((_ACTOR_EVIDENCE, _SOURCE_EVIDENCE)))
_PRODUCER = ProducerIdentity("synthetic-review-recorder", "1")


def _processor() -> ReviewActorProvenance:
    return ReviewActorProvenance(
        actor_id="synthetic-processor",
        actor_kind=ReviewActorKind.PROCESSOR,
        authority_scope=ReviewAuthorityScope.TECHNICAL_PROCESSOR,
        authority_domain="projectkoios-references",
        verification_record_id=_ACTOR_EVIDENCE,
        verification_method="synthetic implementation attestation",
    )


def _person(
    scope: ReviewAuthorityScope,
    *,
    domain: str = "projectkoios-references",
) -> ReviewActorProvenance:
    return ReviewActorProvenance(
        actor_id="synthetic-person",
        actor_kind=ReviewActorKind.PERSON,
        authority_scope=scope,
        authority_domain=domain,
        verification_record_id=_ACTOR_EVIDENCE,
        verification_method="synthetic repository admission",
    )


def _technical(
    outcome: TechnicalReviewOutcome,
    *,
    subject_id: str = _SUBJECT,
    transition: ReviewTransitionKind = ReviewTransitionKind.INITIAL,
    supersedes: str | None = None,
    observed_at: str = "2026-09-18T12:00:00Z",
) -> TechnicalReviewRecord:
    return TechnicalReviewRecord.create(
        subject_id=subject_id,
        context_id="synthetic-collection",
        technical_kind=TechnicalReviewKind.TRANSCRIPTION,
        outcome=outcome,
        producer=_PRODUCER,
        transition_kind=transition,
        actor=_processor(),
        evidence_ids=_EVIDENCE,
        rationale="Synthetic processor result linked to exact evidence.",
        observed_at=observed_at,
        supersedes_record_id=supersedes,
    )


def _reading(
    decision: ReadingDecision,
    *,
    transition: ReviewTransitionKind = ReviewTransitionKind.INITIAL,
    supersedes: str | None = None,
    decided_at: str = "2026-09-18T12:01:00Z",
) -> HumanReviewDecision:
    return HumanReviewDecision.create(
        subject_id=_SUBJECT,
        context_id="synthetic-collection",
        dimension=HumanReviewDimension.READING,
        decision=decision,
        producer=_PRODUCER,
        transition_kind=transition,
        actor=_person(ReviewAuthorityScope.REFERENCE_READER),
        evidence_ids=_EVIDENCE,
        rationale="Synthetic reading decision linked to exact evidence.",
        decided_at=decided_at,
        supersedes_decision_id=supersedes,
    )


def test__review_records__replace_scalar_without_crossing_boundaries() -> None:
    assert not hasattr(public_api, "ReviewStatus")
    assert not hasattr(public_api, "ReviewMembership")
    assert {item.value for item in HumanReviewDimension} == {
        "reading",
        "claim-support-check",
        "review-collection-inclusion",
    }


def test__review_records__separate_processor_and_human_authority() -> None:
    with pytest.raises(ReviewRecordError, match="requires a person"):
        ReviewActorProvenance(
            actor_id="processor",
            actor_kind=ReviewActorKind.PROCESSOR,
            authority_scope=ReviewAuthorityScope.REFERENCE_READER,
            authority_domain="projectkoios-references",
            verification_record_id=_ACTOR_EVIDENCE,
            verification_method="synthetic",
        )

    person = _person(ReviewAuthorityScope.REFERENCE_READER)
    with pytest.raises(ReviewRecordError, match="technical processor"):
        TechnicalReviewRecord.create(
            subject_id=_SUBJECT,
            context_id="synthetic-collection",
            technical_kind=TechnicalReviewKind.DISCOVERY,
            outcome=TechnicalReviewOutcome.OBSERVED,
            producer=_PRODUCER,
            transition_kind=ReviewTransitionKind.INITIAL,
            actor=person,
            evidence_ids=_EVIDENCE,
            rationale="Synthetic evidence.",
            observed_at="2026-09-18T12:00:00Z",
        )

    processor = _processor()
    with pytest.raises(ReviewRecordError, match="requires reference-reader"):
        HumanReviewDecision.create(
            subject_id=_SUBJECT,
            context_id="synthetic-collection",
            dimension=HumanReviewDimension.READING,
            decision=ReadingDecision.READ,
            producer=_PRODUCER,
            transition_kind=ReviewTransitionKind.INITIAL,
            actor=processor,
            evidence_ids=_EVIDENCE,
            rationale="Synthetic evidence.",
            decided_at="2026-09-18T12:00:00Z",
        )


def test__human_decisions__enforce_domain_and_dimension() -> None:
    with pytest.raises(
        ReviewRecordError, match="owning scientific application"
    ):
        HumanReviewDecision.create(
            subject_id=_SUBJECT,
            context_id=_CLAIM,
            dimension=HumanReviewDimension.CLAIM_SUPPORT_CHECK,
            decision=ClaimSupportCheckDecision.CHECKED,
            producer=_PRODUCER,
            transition_kind=ReviewTransitionKind.INITIAL,
            actor=_person(ReviewAuthorityScope.SCIENTIFIC_CLAIM_REVIEWER),
            evidence_ids=_EVIDENCE,
            rationale="Synthetic check.",
            decided_at="2026-09-18T12:00:00Z",
        )

    scientific = HumanReviewDecision.create(
        subject_id=_SUBJECT,
        context_id=_CLAIM,
        dimension=HumanReviewDimension.CLAIM_SUPPORT_CHECK,
        decision=ClaimSupportCheckDecision.CHECKED,
        producer=_PRODUCER,
        transition_kind=ReviewTransitionKind.INITIAL,
        actor=_person(
            ReviewAuthorityScope.SCIENTIFIC_CLAIM_REVIEWER,
            domain="synthetic-research-owner",
        ),
        evidence_ids=_EVIDENCE,
        rationale="Checked support; this does not accept the claim.",
        decided_at="2026-09-18T12:00:00Z",
    )
    inclusion = HumanReviewDecision.create(
        subject_id=_SUBJECT,
        context_id="synthetic-collection",
        dimension=HumanReviewDimension.REVIEW_COLLECTION_INCLUSION,
        decision=ReviewInclusionDecision.UNRESOLVED,
        producer=_PRODUCER,
        transition_kind=ReviewTransitionKind.INITIAL,
        actor=_person(ReviewAuthorityScope.REVIEW_COLLECTION_CURATOR),
        evidence_ids=_EVIDENCE,
        rationale="Collection membership remains unresolved.",
        decided_at="2026-09-18T12:00:00Z",
    )

    projection = replay_review_records((), (scientific, inclusion))
    assert len(projection.current_human_decision_ids) == 2
    assert {item.dimension for item in projection.human_decision_history} == {
        HumanReviewDimension.CLAIM_SUPPORT_CHECK,
        HumanReviewDimension.REVIEW_COLLECTION_INCLUSION,
    }


def test__records__require_actor_evidence_rationale_and_canonical_time() -> (
    None
):
    with pytest.raises(ReviewRecordError, match="omits actor verification"):
        TechnicalReviewRecord.create(
            subject_id=_SUBJECT,
            context_id="synthetic-collection",
            technical_kind=TechnicalReviewKind.DISCOVERY,
            outcome=TechnicalReviewOutcome.OBSERVED,
            transition_kind=ReviewTransitionKind.INITIAL,
            actor=_processor(),
            producer=_PRODUCER,
            evidence_ids=(_SOURCE_EVIDENCE,),
            rationale="Synthetic evidence.",
            observed_at="2026-09-18T12:00:00Z",
        )
    with pytest.raises(ReviewRecordError, match="bounded non-empty"):
        _person(ReviewAuthorityScope.REFERENCE_READER).__class__(
            actor_id="",
            actor_kind=ReviewActorKind.PERSON,
            authority_scope=ReviewAuthorityScope.REFERENCE_READER,
            authority_domain="projectkoios-references",
            verification_record_id=_ACTOR_EVIDENCE,
            verification_method="synthetic",
        )
    with pytest.raises(ReviewRecordError, match="canonical UTC"):
        TechnicalReviewRecord.create(
            subject_id=_SUBJECT,
            context_id="synthetic-collection",
            technical_kind=TechnicalReviewKind.DISCOVERY,
            outcome=TechnicalReviewOutcome.OBSERVED,
            transition_kind=ReviewTransitionKind.INITIAL,
            actor=_processor(),
            producer=_PRODUCER,
            evidence_ids=_EVIDENCE,
            rationale="Synthetic evidence.",
            observed_at="now",
        )


def test__records__bind_producer_and_effective_io_limits() -> None:
    record = _technical(TechnicalReviewOutcome.PASSED)
    data = json.loads(record.to_json())
    data["producer"]["version"] = "changed"
    tampered = (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ReviewRecordError, match="identity does not match"):
        TechnicalReviewRecord.from_json(tampered)

    projection = replay_review_records((record,), ())
    assert projection.producer.name == "projectkoios.references.review-replay"
    assert projection.effective_limits == REVIEW_IO_LIMITS
    assert projection.effective_limits_id == REVIEW_IO_LIMITS.evidence_id
    assert projection.effective_limits_id == (
        "reference-io-limits:sha256:"
        "040988955e60b41ba210b5bfc82c199af49414691c7f105d9f113e0d8863f49f"
    )


@pytest.mark.parametrize(
    ("container", "field"),
    (
        ("actor", "actor_kind"),
        ("actor", "authority_scope"),
        (None, "technical_kind"),
        (None, "outcome"),
        (None, "transition_kind"),
    ),
)
def test__technical_review_json__normalizes_malformed_enums(
    container: str | None,
    field: str,
) -> None:
    data = json.loads(_technical(TechnicalReviewOutcome.PASSED).to_json())
    target = data if container is None else data[container]
    target[field] = "invalid-enum-value"
    malformed = (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ReviewRecordError, match=f"{field} is invalid"):
        TechnicalReviewRecord.from_json(malformed)


@pytest.mark.parametrize("field", ("dimension", "transition_kind"))
def test__human_review_json__normalizes_malformed_enums(field: str) -> None:
    data = json.loads(_reading(ReadingDecision.READ).to_json())
    data[field] = "invalid-enum-value"
    malformed = (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ReviewRecordError, match=f"{field} is invalid"):
        HumanReviewDecision.from_json(malformed)


def test__review_json__rejects_size_and_depth_before_parser_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_parser(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("JSON parser was called before review preflight")

    monkeypatch.setattr(
        "projectkoios.references.review.json.loads",
        forbidden_parser,
    )
    maximum_bytes = REVIEW_IO_LIMITS.max_json_bytes
    maximum_depth = REVIEW_IO_LIMITS.max_json_depth
    assert maximum_bytes is not None
    assert maximum_depth is not None

    oversized = '{"value":"' + "x" * maximum_bytes + '"}'
    with pytest.raises(ReferenceIOLimitError) as size_failure:
        TechnicalReviewRecord.from_json(oversized)
    assert size_failure.value.coverage_status == "incomplete"
    assert size_failure.value.limit_name == "max_json_bytes"
    assert size_failure.value.limits == REVIEW_IO_LIMITS

    deeply_nested = "[" * (maximum_depth + 1) + "]" * (maximum_depth + 1)
    with pytest.raises(ReferenceIOLimitError) as depth_failure:
        ReviewProjection.from_json(deeply_nested)
    assert depth_failure.value.coverage_status == "incomplete"
    assert depth_failure.value.limit_name == "max_json_depth"
    assert (
        depth_failure.value.to_dict()["effective_limits_id"]
        == REVIEW_IO_LIMITS.evidence_id
    )


def test__review_projection__rejects_direct_construction() -> None:
    with pytest.raises(ReviewRecordError, match="only be created by replay"):
        ReviewProjection()


def test__replay__is_order_independent_and_retains_corrections() -> None:
    initial = _reading(ReadingDecision.READ)
    correction = _reading(
        ReadingDecision.NOT_ESTABLISHED,
        transition=ReviewTransitionKind.CORRECTION,
        supersedes=initial.decision_id,
    )
    technical_initial = _technical(TechnicalReviewOutcome.PASSED)
    technical_changed = _technical(
        TechnicalReviewOutcome.FAILED,
        transition=ReviewTransitionKind.SUPERSESSION,
        supersedes=technical_initial.record_id,
    )

    first = replay_review_records(
        (technical_changed, technical_initial),
        (correction, initial),
    )
    second = replay_review_records(
        (technical_initial, technical_changed),
        (initial, correction),
    )

    assert first == second
    assert first.current_human_decision_ids == (correction.decision_id,)
    assert first.current_technical_record_ids == (technical_changed.record_id,)
    assert first.human_decision_history == (initial, correction)
    assert first.technical_history == (technical_initial, technical_changed)
    assert ReviewProjection.from_json(first.to_json()) == first


def test__replay__rejects_invalid_or_concurrent_transitions() -> None:
    initial = _reading(ReadingDecision.READ)
    unprovenanced = _reading(ReadingDecision.NOT_ESTABLISHED)
    with pytest.raises(ReviewRecordError, match="exactly one initial"):
        replay_review_records((), (initial, unprovenanced))

    first_branch = _reading(
        ReadingDecision.NOT_ESTABLISHED,
        transition=ReviewTransitionKind.CORRECTION,
        supersedes=initial.decision_id,
    )
    other_branch = HumanReviewDecision.create(
        subject_id=_SUBJECT,
        context_id="synthetic-collection",
        dimension=HumanReviewDimension.READING,
        decision=ReadingDecision.NOT_ESTABLISHED,
        transition_kind=ReviewTransitionKind.SUPERSESSION,
        actor=_person(ReviewAuthorityScope.REFERENCE_READER),
        evidence_ids=_EVIDENCE,
        producer=_PRODUCER,
        rationale="Independent concurrent synthetic branch.",
        decided_at="2026-09-18T12:02:00Z",
        supersedes_decision_id=initial.decision_id,
    )
    with pytest.raises(ReviewRecordError, match="concurrent conflicting"):
        replay_review_records((), (initial, first_branch, other_branch))

    unchanged = _reading(
        ReadingDecision.READ,
        transition=ReviewTransitionKind.SUPERSESSION,
        supersedes=initial.decision_id,
    )
    with pytest.raises(ReviewRecordError, match="does not change"):
        replay_review_records((), (initial, unchanged))

    regression = _reading(
        ReadingDecision.NOT_ESTABLISHED,
        transition=ReviewTransitionKind.SUPERSESSION,
        supersedes=initial.decision_id,
    )
    with pytest.raises(ReviewRecordError, match="requires a correction"):
        replay_review_records((), (initial, regression))


def test__replay__rejects_supersession_chronology_regression() -> None:
    reading = _reading(
        ReadingDecision.READ,
        decided_at="2026-09-18T12:05:00Z",
    )
    reading_correction = _reading(
        ReadingDecision.NOT_ESTABLISHED,
        transition=ReviewTransitionKind.CORRECTION,
        supersedes=reading.decision_id,
        decided_at="2026-09-18T12:04:59Z",
    )
    with pytest.raises(ReviewRecordError, match="timestamp precedes"):
        replay_review_records((), (reading, reading_correction))

    technical = _technical(
        TechnicalReviewOutcome.PASSED,
        observed_at="2026-09-18T12:05:00Z",
    )
    technical_change = _technical(
        TechnicalReviewOutcome.FAILED,
        transition=ReviewTransitionKind.SUPERSESSION,
        supersedes=technical.record_id,
        observed_at="2026-09-18T12:04:59Z",
    )
    with pytest.raises(ReviewRecordError, match="timestamp precedes"):
        replay_review_records((technical, technical_change), ())


def test__projection__rejects_derived_state_tampering() -> None:
    projection = replay_review_records(
        (_technical(TechnicalReviewOutcome.PASSED),), ()
    )
    data = json.loads(projection.to_json())
    data["current_technical_record_ids"] = []
    tampered = (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ReviewRecordError, match="tampered"):
        ReviewProjection.from_json(tampered)


def test__catalog_review__round_trips_history_and_exact_replay(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(
        tmp_path / "synthetic-review.sqlite3",
        storage_class=RootStorageClass.LOCAL,
    )
    catalog.initialize()
    technical = _technical(TechnicalReviewOutcome.PASSED)
    reading = _reading(ReadingDecision.READ)
    correction = _reading(
        ReadingDecision.NOT_ESTABLISHED,
        transition=ReviewTransitionKind.CORRECTION,
        supersedes=reading.decision_id,
    )

    catalog.import_review_records((technical,), (correction, reading))
    first = catalog.export_review_json()
    catalog.import_review_records((technical,), (reading, correction))

    projection = catalog.read_review_projection()
    assert catalog.export_review_json() == first
    assert projection.human_decision_history == (reading, correction)
    assert projection.current_human_decision_ids == (correction.decision_id,)
    assert catalog.counts()["technical_review_records"] == 1
    assert catalog.counts()["human_review_decisions"] == 2


def test__catalog_review__concurrent_batch_rolls_back_atomically(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(
        tmp_path / "synthetic-conflict.sqlite3",
        storage_class=RootStorageClass.LOCAL,
    )
    catalog.initialize()
    initial = _reading(ReadingDecision.READ)
    catalog.import_review_records((), (initial,))
    first_branch = _reading(
        ReadingDecision.NOT_ESTABLISHED,
        transition=ReviewTransitionKind.CORRECTION,
        supersedes=initial.decision_id,
    )
    other_branch = HumanReviewDecision.create(
        subject_id=_SUBJECT,
        context_id="synthetic-collection",
        dimension=HumanReviewDimension.READING,
        decision=ReadingDecision.NOT_ESTABLISHED,
        transition_kind=ReviewTransitionKind.SUPERSESSION,
        actor=_person(ReviewAuthorityScope.REFERENCE_READER),
        evidence_ids=_EVIDENCE,
        producer=_PRODUCER,
        rationale="Concurrent synthetic branch.",
        decided_at="2026-09-18T12:03:00Z",
        supersedes_decision_id=initial.decision_id,
    )

    with pytest.raises(CatalogConflictError, match="concurrent conflicting"):
        catalog.import_review_records((), (first_branch, other_branch))
    assert catalog.read_review_projection().human_decision_history == (initial,)

    catalog.import_review_records((), (first_branch,))
    with pytest.raises(CatalogConflictError, match="concurrent conflicting"):
        catalog.import_review_records((), (other_branch,))
    assert catalog.read_review_projection().human_decision_history == (
        initial,
        first_branch,
    )


def test__catalog_review__rejects_producer_scalar_tampering(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic-tamper.sqlite3"
    catalog = ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)
    catalog.initialize()
    technical = _technical(TechnicalReviewOutcome.PASSED)
    catalog.import_review_records((technical,), ())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE technical_review_records "
            "SET producer_name = 'tampered-producer'"
        )
    with pytest.raises(CatalogSchemaError, match="differs from canonical"):
        catalog.read_review_projection()


def test__catalog_review__bounds_iterable_before_materializing(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(
        tmp_path / "synthetic-iterable-limit.sqlite3",
        storage_class=RootStorageClass.LOCAL,
    )
    catalog.initialize()
    record = _technical(TechnicalReviewOutcome.PASSED)
    observed = 0

    def unbounded_records() -> Iterator[TechnicalReviewRecord]:
        nonlocal observed
        while True:
            observed += 1
            yield record

    maximum = REVIEW_IO_LIMITS.max_entries
    assert maximum is not None
    with pytest.raises(ReviewRecordError, match="record limit"):
        catalog.import_review_records(unbounded_records(), ())

    assert observed == maximum + 1
    assert catalog.counts()["technical_review_records"] == 0


def test__catalog_review__preflights_catalog_record_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic-row-limit.sqlite3"
    catalog = ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)
    catalog.initialize()
    maximum = REVIEW_IO_LIMITS.max_entries
    assert maximum is not None

    with sqlite3.connect(path) as connection:
        for index in range(maximum + 1):
            record = _technical(
                TechnicalReviewOutcome.PASSED,
                subject_id=("reference-candidate:sha256:" + f"{index:064x}"),
            )
            connection.execute(
                """
                INSERT INTO technical_review_records(
                    record_id, record_schema_version, authority_kind,
                    producer_name, producer_version, effective_limits_id,
                    subject_id, context_id, technical_kind, outcome,
                    transition_kind, actor_id, actor_kind, authority_scope,
                    authority_domain, verification_record_id, observed_at,
                    supersedes_record_id, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.schema_version,
                    record.authority_kind,
                    record.producer.name,
                    record.producer.version,
                    record.effective_limits_id,
                    record.subject_id,
                    record.context_id,
                    record.technical_kind.value,
                    record.outcome.value,
                    record.transition_kind.value,
                    record.actor.actor_id,
                    record.actor.actor_kind.value,
                    record.actor.authority_scope.value,
                    record.actor.authority_domain,
                    record.actor.verification_record_id,
                    record.observed_at,
                    record.supersedes_record_id,
                    record.to_json(),
                ),
            )

    with pytest.raises(CatalogSchemaError, match="record limit"):
        catalog.read_review_projection()


def test__catalog_review__preflights_catalog_json_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic-json-limit.sqlite3"
    catalog = ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)
    catalog.initialize()
    catalog.import_review_records(
        (_technical(TechnicalReviewOutcome.PASSED),), ()
    )
    maximum = REVIEW_IO_LIMITS.max_json_bytes
    assert maximum is not None

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE technical_review_records "
            "SET record_json = CAST(zeroblob(?) AS TEXT)",
            (maximum + 1,),
        )

    with pytest.raises(CatalogSchemaError, match="JSON byte limit"):
        catalog.read_review_projection()
