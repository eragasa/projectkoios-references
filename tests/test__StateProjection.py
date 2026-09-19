from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import projectkoios.references.catalog as catalog_module
import projectkoios.references.state_projection as state_projection_module
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
from projectkoios.references.assets import (
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    SearchRoot,
)
from projectkoios.references.catalog import CatalogSchemaError, ReferenceCatalog
from projectkoios.references.collection_reconciliation import (
    load_collection_rows,
)
from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CandidateVersionRelation,
    CoverageAccessState,
    CoverageCandidate,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
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
from projectkoios.references.state_projection import (
    STATE_FIELD_RULES,
    ReferenceStateProjection,
    StateClaim,
    StateKnowledge,
    StateProjectionError,
    StateRecordKind,
    StateResolution,
    acquisition_state_claims,
    asset_candidate_state_claims,
    build_reference_state_projection,
    candidate_state_claims,
    projection_from_csv,
    projection_to_biblatex,
    projection_to_csv,
    replay_reference_state,
)

_SUBJECT = "reference-candidate:sha256:" + "1" * 64
_INPUT_A = "synthetic-observation:sha256:" + "a" * 64
_INPUT_B = "synthetic-observation:sha256:" + "b" * 64
_ACTOR = "actor-verification:sha256:" + "c" * 64


def _candidate() -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey="synthetic2026",
        entry_type="article",
        title="Synthetic state projection",
        authors=("Example, Ada", "Example, Ben"),
        year="2026",
        doi="10.1234/synthetic",
        isbn=None,
        url="https://example.test/synthetic",
        eprint=None,
        source_observation_ids=("bibliography-observation:sha256:" + "d" * 64,),
        generator=ProducerIdentity("synthetic-normalizer", "1"),
    )


def _acquisition() -> AcquisitionProjection:
    return AcquisitionProjection(
        contract_id=ACQUISITION_CONTRACT_ID,
        contract_version=ACQUISITION_CONTRACT_VERSION,
        contract_status=ACQUISITION_CONTRACT_STATUS,
        manifest_id="acquisition-manifest:sha256:" + "e" * 64,
        normalized_input_id="acquisition-input:sha256:" + "f" * 64,
        source_id="synthetic-private-input",
        proposed_citekey="synthetic2026",
        identity_status="unaccepted-candidate",
        citekey_status="proposed-noncanonical",
        manuscript_status="not-assessed",
        source_content_id="blob:sha256:" + "0" * 64,
        source_sha256="0" * 64,
        source_byte_size=123,
        root_alias="synthetic-staging",
        relative_path="synthetic2026.pdf",
        acquisition=AcquisitionObservation(
            "operator-asserted-lawfully-held", "operator-assertion"
        ),
        access=AccessObservation(
            "private-local-bytes-observed", "operator-assertion"
        ),
        rights=RightsObservation(
            "cc-by-4.0-operator-asserted", "operator-assertion"
        ),
        doi="10.1234/synthetic-conflict",
        source_url="https://example.test/synthetic.pdf",
        source_version="published-version",
    )


def _review(candidate_id: str):
    decision = HumanReviewDecision.create(
        subject_id=candidate_id,
        context_id="synthetic-collection",
        dimension=HumanReviewDimension.READING,
        decision=ReadingDecision.READ,
        producer=ProducerIdentity("synthetic-review-recorder", "1"),
        transition_kind=ReviewTransitionKind.INITIAL,
        actor=ReviewActorProvenance(
            actor_id="synthetic-reader",
            actor_kind=ReviewActorKind.PERSON,
            authority_scope=ReviewAuthorityScope.REFERENCE_READER,
            authority_domain="projectkoios-references",
            verification_record_id=_ACTOR,
            verification_method="synthetic repository admission",
        ),
        evidence_ids=tuple(sorted((_ACTOR, _INPUT_A))),
        rationale="Synthetic actor-provenanced reading decision.",
        decided_at="2026-09-19T00:00:00Z",
    )
    return replay_review_records((), (decision,))


def _field_value(field: str) -> object:
    if field == "candidate_id":
        return _SUBJECT
    if field == "identity_status":
        return "unaccepted-candidate"
    if field == "proposed_citekey":
        return "synthetic2026"
    if field == "citekey_status":
        return "proposed-noncanonical"
    if field in {
        "authors",
        "source_bibliographies",
        "asset_competing_observation_ids",
        "asset_alternate_version_observation_ids",
    }:
        return ("asset-heuristic-observation:sha256:" + "e" * 64,)
    if field == "asset_sha256":
        return "f" * 64
    if field == "asset_byte_size":
        return 1
    if field == "asset_ambiguity_status":
        return "unresolved-single-heuristic-candidate"
    if field == "asset_heuristic_observations":
        return (
            {
                "kind": "title-token-overlap",
                "matched_tokens": ["synthetic"],
                "compared_token_count": 1,
            },
        )
    if field == "technical_review_status":
        return {"kind": "discovery", "outcome": "observed"}
    if field == "reading_decision":
        return "read"
    if field == "claim_support_check":
        return "checked"
    if field == "collection_inclusion":
        return "included"
    return "synthetic-value"


def test__state_projection__round_trips_every_authority_field() -> None:
    claims = tuple(
        StateClaim.observed(
            subject_id=_SUBJECT,
            field=field,
            value=_field_value(field),
            record_kind=rule.allowed_record_kinds[0],
            authority_owner=rule.authority_owner,
            authoritative_input_id=_INPUT_A,
            source_locator=f"synthetic/{field}",
        )
        for field, rule in sorted(STATE_FIELD_RULES.items())
        if rule.allowed_record_kinds[0] is not StateRecordKind.HUMAN_DECISION
    )
    projection = replay_reference_state(
        subject_id=_SUBJECT,
        claims=reversed(claims),
        authoritative_input_ids=(_INPUT_A,),
        exclusions=("synthetic fixture only",),
    )

    assert (
        ReferenceStateProjection.from_json(projection.to_json()) == projection
    )
    csv_text = projection_to_csv(projection)
    assert projection_from_csv(csv_text) == projection
    assert projection_to_csv(projection_from_csv(csv_text)) == csv_text
    assert all(
        field.resolution
        is (
            StateResolution.SINGLE
            if field.values
            else StateResolution.NOT_OBSERVED
        )
        for field in projection.fields
    )


def test__state_projection__large_metadata_csv_is_bounded_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    claims = candidate_state_claims(candidate)
    exclusions = tuple(f"{index:03d}-" + "x" * 4000 for index in range(128))
    projection = replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=claims,
        authoritative_input_ids=(candidate.candidate_id,),
        exclusions=exclusions,
    )
    csv_text = projection_to_csv(projection)
    assert projection_from_csv(csv_text) == projection
    assert csv_text.count(exclusions[0]) == 1

    monkeypatch.setattr(
        state_projection_module,
        "_MAX_PROJECTION_CSV_BYTES",
        len(csv_text.encode("utf-8")) - 1,
    )
    with pytest.raises(StateProjectionError, match="CSV exceeds"):
        projection_to_csv(projection)


def test__state_projection__retains_conflicts_instead_of_last_writer() -> None:
    first = StateClaim.observed(
        subject_id=_SUBJECT,
        field="rights_status",
        value="source-asserts-open",
        record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
        authoritative_input_id=_INPUT_A,
        source_locator="source-a/rights",
    )
    second = StateClaim.observed(
        subject_id=_SUBJECT,
        field="rights_status",
        value="source-asserts-restricted",
        record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
        authoritative_input_id=_INPUT_B,
        source_locator="source-b/rights",
    )

    projection = replay_reference_state(
        subject_id=_SUBJECT,
        claims=(second, first),
        authoritative_input_ids=(_INPUT_B, _INPUT_A),
    )
    rights = projection.field("rights_status")
    assert rights.resolution is StateResolution.DISCREPANCY
    assert [value.value() for value in rights.values] == [
        "source-asserts-open",
        "source-asserts-restricted",
    ]
    assert projection.authoritative_input_ids == (_INPUT_A, _INPUT_B)

    with pytest.raises(StateProjectionError, match="authority owner"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="rights_status",
            value="accepted",
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authority_owner="owning-publication-repository",
            authoritative_input_id=_INPUT_A,
            source_locator="invalid",
        )
    with pytest.raises(StateProjectionError, match="absolute or traversing"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="rights_status",
            value="unresolved",
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=_INPUT_A,
            source_locator="/absolute/path/not-allowed.json",
        )


def test__state_projection__rejects_untyped_values_and_decisions() -> None:
    with pytest.raises(StateProjectionError, match="unsupported"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="identity_status",
            value="accepted-reference",
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/identity",
        )
    with pytest.raises(StateProjectionError, match="positive integer"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="asset_byte_size",
            value="100",
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/size",
        )
    with pytest.raises(StateProjectionError, match="unsupported"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="asset_ambiguity_status",
            value="resolved-by-score",
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/ambiguity",
        )
    with pytest.raises(StateProjectionError, match="heuristic_observations"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="asset_heuristic_observations",
            value=(
                {
                    "kind": "fabricated-strong-match",
                    "matched_tokens": ["synthetic"],
                    "compared_token_count": 1,
                },
            ),
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/heuristics",
        )
    with pytest.raises(StateProjectionError, match="asset observation"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="asset_competing_observation_ids",
            value=("not-a-content-identity",),
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/competition",
        )
    with pytest.raises(StateProjectionError, match="canonical JSON"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="title",
            value=float("nan"),
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/title",
        )
    with pytest.raises(StateProjectionError, match="typed actor-provenanced"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="reading_decision",
            value="read",
            record_kind=StateRecordKind.HUMAN_DECISION,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/reading",
            actor_id="fabricated",
            authority_scope="reference-reader",
            actor_verification_record_id=_ACTOR,
        )
    with pytest.raises(StateProjectionError, match="unsupported state field"):
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="publication_status",
            value="accepted",
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/publication",
        )


def test__persisted_projection__revalidates_asset_values_and_authority() -> (
    None
):
    candidate = _candidate()
    asset_id = "asset-heuristic-observation:sha256:" + "e" * 64
    claims = (
        StateClaim.observed(
            subject_id=candidate.candidate_id,
            field="asset_ambiguity_status",
            value="unresolved-single-heuristic-candidate",
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/ambiguity",
        ),
        StateClaim.observed(
            subject_id=candidate.candidate_id,
            field="asset_heuristic_observations",
            value=(
                {
                    "kind": "title-token-overlap",
                    "matched_tokens": ["synthetic"],
                    "compared_token_count": 1,
                },
            ),
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/heuristics",
        ),
        StateClaim.observed(
            subject_id=candidate.candidate_id,
            field="asset_competing_observation_ids",
            value=(asset_id,),
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=_INPUT_A,
            source_locator="synthetic/competition",
        ),
    )
    projection = replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=(*candidate_state_claims(candidate), *claims),
        authoritative_input_ids=(candidate.candidate_id, _INPUT_A),
    )

    def tampered_json(
        field: str,
        *,
        value: object | None = None,
        record_kind: str | None = None,
    ) -> str:
        data = json.loads(projection.to_json())
        raw_field = next(
            item for item in data["fields"] if item["field"] == field
        )
        raw_value = raw_field["values"][0]
        if value is not None:
            raw_value["value_json"] = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        if record_kind is not None:
            raw_value["record_kinds"] = [record_kind]
        payload = dict(data)
        payload.pop("projection_id")
        data["projection_id"] = state_projection_module._stable_id(
            "reference-state-projection", payload
        )
        return state_projection_module._pretty_json(data)

    invalid_values = (
        (
            "asset_ambiguity_status",
            "resolved-by-score",
            "unsupported",
        ),
        (
            "asset_heuristic_observations",
            [
                {
                    "kind": "fabricated-strong-match",
                    "matched_tokens": ["synthetic"],
                    "compared_token_count": 1,
                }
            ],
            "heuristic_observations",
        ),
        (
            "asset_competing_observation_ids",
            ["not-a-content-identity"],
            "asset observation",
        ),
    )
    for field, value, message in invalid_values:
        with pytest.raises(StateProjectionError, match=message):
            ReferenceStateProjection.from_json(
                tampered_json(field, value=value)
            )
    with pytest.raises(StateProjectionError, match="record kind"):
        ReferenceStateProjection.from_json(
            tampered_json(
                "asset_ambiguity_status",
                record_kind="immutable-observation",
            )
        )

    csv_text = projection_to_csv(projection)
    tampered_csv = csv_text.replace(
        '"""unresolved-single-heuristic-candidate"""',
        '"""resolved-by-score"""',
    )
    assert tampered_csv != csv_text
    with pytest.raises(StateProjectionError, match="unsupported"):
        projection_from_csv(tampered_csv)


def test__state_projection__bounds_iterables_and_aggregate_bytes() -> None:
    consumed = 0

    def unbounded_claims():  # type: ignore[no-untyped-def]
        nonlocal consumed
        while True:
            consumed += 1
            yield StateClaim.observed(
                subject_id=_SUBJECT,
                field="rights_status",
                value="unresolved",
                record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                authoritative_input_id=_INPUT_A,
                source_locator="synthetic/rights",
            )

    with pytest.raises(StateProjectionError, match="record limit"):
        replay_reference_state(
            subject_id=_SUBJECT,
            claims=unbounded_claims(),
            authoritative_input_ids=(_INPUT_A,),
        )
    assert consumed == 4097

    large_claims = tuple(
        StateClaim.observed(
            subject_id=_SUBJECT,
            field="rights_status",
            value=f"{index:04d}-" + "x" * 3900,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=_INPUT_A,
            source_locator=f"synthetic/rights-{index}",
        )
        for index in range(1100)
    )
    with pytest.raises(StateProjectionError, match="aggregate byte limit"):
        replay_reference_state(
            subject_id=_SUBJECT,
            claims=large_claims,
            authoritative_input_ids=(_INPUT_A,),
        )


def test__state_projection__distinguishes_absence_states() -> None:
    claims = tuple(
        StateClaim.unavailable(
            subject_id=_SUBJECT,
            field=field,
            knowledge=knowledge,
            authoritative_input_id=_INPUT_A,
            source_locator=f"synthetic/{field}",
        )
        for field, knowledge in (
            ("access_status", StateKnowledge.UNKNOWN),
            ("rights_status", StateKnowledge.NOT_OBSERVED),
            ("asset_status", StateKnowledge.NOT_APPLICABLE),
        )
    )
    projection = replay_reference_state(
        subject_id=_SUBJECT,
        claims=claims,
        authoritative_input_ids=(_INPUT_A,),
    )
    assert (
        projection.field("access_status").values[0].knowledge
        is StateKnowledge.UNKNOWN
    )
    assert (
        projection.field("rights_status").values[0].knowledge
        is StateKnowledge.NOT_OBSERVED
    )
    assert (
        projection.field("asset_status").values[0].knowledge
        is StateKnowledge.NOT_APPLICABLE
    )
    assert "publication_status" not in STATE_FIELD_RULES


def test__state_projection__composes_published_evidence() -> None:
    candidate = _candidate()
    acquisition = _acquisition()
    projection = build_reference_state_projection(
        candidate=candidate,
        collection_id="synthetic-collection",
        acquisition=acquisition,
        review=_review(candidate.candidate_id),
    )

    assert projection.field("access_status").values[0].value() == (
        "private-local-bytes-observed"
    )
    assert projection.field("rights_status").values[0].value() == (
        "cc-by-4.0-operator-asserted"
    )
    assert projection.field("acquisition_status").values[0].value() == (
        "operator-asserted-lawfully-held"
    )
    assert projection.field("reading_decision").values[0].value() == "read"
    assert projection.field("doi").resolution is StateResolution.DISCREPANCY
    protected_fields = {
        "canonical_identity_status",
        "rights_decision",
        "scientific_support_decision",
        "manuscript_status",
        "publication_status",
        "contract_status",
    }
    assert protected_fields.isdisjoint(STATE_FIELD_RULES)
    assert any("canonical identity" in item for item in projection.exclusions)
    assert any("scientific support" in item for item in projection.exclusions)
    assert any("manuscript use" in item for item in projection.exclusions)
    assert any("publication" in item for item in projection.exclusions)
    assert any("contract acceptance" in item for item in projection.exclusions)
    assert acquisition.manifest_id in projection.authoritative_input_ids

    biblatex = projection_to_biblatex(projection)
    assert biblatex.startswith("@article{synthetic2026,")
    assert "doi =" not in biblatex
    assert projection.projection_id in biblatex
    assert "non-authoritative-projection" in biblatex


def test__state_projection__rejects_tampering_and_undeclared_inputs() -> None:
    candidate = _candidate()
    claims = candidate_state_claims(candidate)
    with pytest.raises(StateProjectionError, match="undeclared"):
        replay_reference_state(
            subject_id=candidate.candidate_id,
            claims=claims,
            authoritative_input_ids=(_INPUT_A,),
        )

    projection = replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=claims,
        authoritative_input_ids=(candidate.candidate_id,),
    )
    data = json.loads(projection.to_json())
    data["fields"][0]["authority_owner"] = "last-writer"
    tampered = (
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    with pytest.raises(StateProjectionError, match="authority owner"):
        ReferenceStateProjection.from_json(tampered)


def test__collection_rows__bind_exact_csv_bytes(tmp_path: Path) -> None:
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"
    first_path.write_text(
        "citekey,source_bibliographies,bibliographic_status,reading_status\n"
        "synthetic2026,source.bib,observed,unread\n",
        encoding="utf-8",
    )
    second_path.write_text(
        "citekey,source_bibliographies,bibliographic_status,reading_status\n"
        '"synthetic2026","source.bib","observed","unread"\n',
        encoding="utf-8",
    )
    first = load_collection_rows(
        first_path,
        storage_class=RootStorageClass.LOCAL,
    )["synthetic2026"]
    second = load_collection_rows(
        second_path,
        storage_class=RootStorageClass.LOCAL,
    )["synthetic2026"]
    assert (
        first.source_bibliographies,
        first.bibliographic_status,
        first.reading_status,
    ) == (
        second.source_bibliographies,
        second.bibliographic_status,
        second.reading_status,
    )
    assert first.source_content_id != second.source_content_id
    assert first.observation_id != second.observation_id

    first_projection = build_reference_state_projection(
        candidate=_candidate(),
        collection_id="synthetic-collection",
        collection_row=first,
    )
    second_projection = build_reference_state_projection(
        candidate=_candidate(),
        collection_id="synthetic-collection",
        collection_row=second,
    )
    assert first_projection.projection_id != second_projection.projection_id
    assert first.observation_id in first_projection.authoritative_input_ids
    assert second.observation_id in second_projection.authoritative_input_ids


def test__asset_plan_adapter__binds_exact_plan_bytes(tmp_path: Path) -> None:
    candidate = _candidate()
    root = tmp_path / "assets"
    root.mkdir()
    (root / "synthetic2026.pdf").write_bytes(b"%PDF-1.4\nsynthetic")
    plan = AssetDiscoveryPlanner().scan(
        (candidate,),
        (SearchRoot("synthetic-assets", root, RootStorageClass.LOCAL),),
    )
    assert len(plan.candidates) == 1
    claims = asset_candidate_state_claims(
        subject_id=candidate.candidate_id,
        candidate=plan.candidates[0],
        plan=plan,
    )
    projection = replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=(*candidate_state_claims(candidate), *claims),
        authoritative_input_ids=tuple(
            sorted(
                {candidate.candidate_id}
                | {item.authoritative_input_id for item in claims}
            )
        ),
    )

    assert (
        projection.field("asset_status").values[0].value()
        == "unresolved-heuristic-observation"
    )
    assert (
        projection.field("asset_ambiguity_status").values[0].value()
        == "unresolved-single-heuristic-candidate"
    )
    plan_id = next(
        item
        for item in projection.authoritative_input_ids
        if item.startswith("asset-discovery-plan:sha256:")
    )
    assert all(
        value.authoritative_input_ids == (plan_id,)
        for field in (
            "asset_sha256",
            "asset_byte_size",
            "asset_root_alias",
            "asset_relative_path",
            "asset_status",
        )
        for value in projection.field(field).values
    )
    noncanonical = json.dumps(json.loads(plan.to_json()), sort_keys=True)
    assert noncanonical != plan.to_json()
    with pytest.raises(ValueError, match="noncanonical"):
        AssetDiscoveryPlan.from_json(noncanonical)


def test__asset_plan_adapter__projects_transitive_connected_ambiguity(
    tmp_path: Path,
) -> None:
    alpha = _candidate()
    beta = ReferenceCandidate.create(
        proposed_citekey="beta2026",
        entry_type="article",
        title="Beta Synthetic Work",
        authors=("B. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "9" * 64,),
        generator=ProducerIdentity("synthetic-test", "1"),
    )
    root = tmp_path / "connected-assets"
    root.mkdir()
    (root / "synthetic2026-beta2026.pdf").write_bytes(b"%PDF shared")
    (root / "beta2026-alternate.pdf").write_bytes(b"%PDF beta alternate")
    plan = AssetDiscoveryPlanner().scan(
        (alpha, beta),
        (SearchRoot("connected", root, RootStorageClass.LOCAL),),
    )
    alpha_asset = next(
        item
        for item in plan.candidates
        if item.candidate_id == alpha.candidate_id
    )
    beta_alternate = next(
        item
        for item in plan.candidates
        if item.relative_path == "beta2026-alternate.pdf"
    )
    claims = asset_candidate_state_claims(
        subject_id=alpha.candidate_id,
        candidate=alpha_asset,
        plan=plan,
    )
    projected = {
        claim.field: json.loads(claim.value_json or "null") for claim in claims
    }

    assert projected["asset_ambiguity_status"] == (
        "unresolved-competing-candidates-and-source-versions"
    )
    assert (
        beta_alternate.observation_id
        in projected["asset_competing_observation_ids"]
    )
    assert (
        beta_alternate.observation_id
        in projected["asset_alternate_version_observation_ids"]
    )


def test__state_projection__retains_all_asset_store_conflicts(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    root = tmp_path / "discovery"
    root.mkdir()
    (root / "synthetic2026.pdf").write_bytes(b"%PDF-1.4\nplan")
    plan = AssetDiscoveryPlanner().scan(
        (candidate,),
        (SearchRoot("plan-root", root, RootStorageClass.LOCAL),),
    )
    coverage = CoverageObservation.create(
        asserted_source_revision="synthetic-revision",
        state=CoverageState.COMPLETE,
        authorized_root_aliases=("coverage-root",),
        exclusions=(),
        failures=(),
        ambiguity_evaluation=AmbiguityEvaluation.EVALUATED,
        references=(
            ReferenceCoverage(
                citekey=candidate.proposed_citekey,
                no_match=False,
                access_state=CoverageAccessState.NONE,
                candidates=(
                    CoverageCandidate(
                        root_alias="coverage-root",
                        relative_path="synthetic2026.pdf",
                        sha256="d" * 64,
                        byte_size=99,
                        version_relation=(
                            CandidateVersionRelation.PRIMARY_OR_UNKNOWN
                        ),
                    ),
                ),
                evidence=("synthetic coverage candidate",),
            ),
        ),
    )
    catalog_asset = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256="e" * 64,
        byte_size=100,
        root_alias="catalog-root",
        relative_path="synthetic2026.pdf",
        rights_status="catalog-rights-unresolved",
        asset_status="catalog-observed",
    )
    projection = build_reference_state_projection(
        candidate=candidate,
        collection_id="synthetic-collection",
        acquisition=_acquisition(),
        coverage=coverage,
        catalog_assets=(catalog_asset,),
        asset_plan=plan,
    )

    assert projection.field("asset_sha256").resolution is (
        StateResolution.DISCREPANCY
    )
    assert len(projection.field("asset_sha256").values) == 4
    assert projection.field("rights_status").resolution is (
        StateResolution.DISCREPANCY
    )
    assert any(
        input_id.startswith("asset-discovery-plan:sha256:")
        for input_id in projection.authoritative_input_ids
    )
    assert coverage.coverage_id in projection.authoritative_input_ids


def test__catalog__retains_deterministic_projection_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bibliography = b"@article{catalog2026,title={Synthetic}}\n"
    observation = SourceBibliographyObservation.create(
        source_id="synthetic-catalog-fixture",
        asserted_source_revision="synthetic-revision",
        source_path="references.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey="catalog2026",
        verbatim_entry=bibliography.decode().strip(),
        parser=ProducerIdentity("synthetic-parser", "1"),
    )
    candidate = ReferenceCandidate.create(
        proposed_citekey="catalog2026",
        entry_type="article",
        title="Synthetic",
        authors=(),
        year="2026",
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("synthetic-normalizer", "1"),
    )
    first = replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=candidate_state_claims(candidate),
        authoritative_input_ids=(candidate.candidate_id,),
    )
    rights_claim = StateClaim.observed(
        subject_id=candidate.candidate_id,
        field="rights_status",
        value="synthetic-rights-observation",
        record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
        authoritative_input_id=_INPUT_A,
        source_locator="synthetic/rights",
    )
    second = replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=(*candidate_state_claims(candidate), rights_claim),
        authoritative_input_ids=(candidate.candidate_id, _INPUT_A),
    )
    path = tmp_path / "catalog.sqlite3"
    catalog = ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)
    catalog.initialize()
    catalog.import_candidates((candidate,), (observation,))
    catalog.import_state_projections((first, second))
    catalog.import_state_projections((first,))

    assert catalog.read_state_projections() == tuple(
        sorted((first, second), key=lambda item: item.projection_id)
    )
    export = json.loads(catalog.export_state_projections_json())
    assert export["exact_replay"] is True
    assert export["authority_boundary"] == (
        "non-authoritative-rebuildable-working-projection"
    )
    assert catalog.counts()["state_projections"] == 2

    with monkeypatch.context() as bounded:
        bounded.setattr(catalog_module, "_MAX_STATE_PROJECTIONS", 2)
        catalog.import_state_projections((first, second))
        consumed = 0

        def unbounded_projections():  # type: ignore[no-untyped-def]
            nonlocal consumed
            while True:
                consumed += 1
                yield first

        with pytest.raises(CatalogSchemaError, match="record limit"):
            catalog.import_state_projections(unbounded_projections())
        assert consumed == 3

    with monkeypatch.context() as bounded:
        bounded.setattr(
            catalog_module,
            "_MAX_STATE_PROJECTION_JSON_BYTES",
            len(first.to_json().encode("utf-8")),
        )
        with pytest.raises(CatalogSchemaError, match="JSON byte limit"):
            catalog.import_state_projections((first, second))
        with pytest.raises(CatalogSchemaError, match="JSON byte limit"):
            catalog.read_state_projections()

    with monkeypatch.context() as bounded:
        bounded.setattr(catalog_module, "_MAX_STATE_PROJECTIONS", 1)
        with pytest.raises(CatalogSchemaError, match="record limit"):
            catalog.read_state_projections()

    with monkeypatch.context() as bounded:
        bounded.setattr(catalog_module, "_MAX_STATE_PROJECTION_EXPORT_BYTES", 1)
        with pytest.raises(CatalogSchemaError, match="export exceeds"):
            catalog.export_state_projections_json()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE reference_state_projections SET projection_json = '{}' "
            "WHERE projection_id = ?",
            (first.projection_id,),
        )
    with pytest.raises(CatalogSchemaError, match="invalid canonical JSON"):
        catalog.schema_info()


def test__acquisition_adapter__keeps_candidate_guardrails() -> None:
    candidate = _candidate()
    claims = acquisition_state_claims(
        subject_id=candidate.candidate_id,
        projection=_acquisition(),
    )
    values = {claim.field: claim.value() for claim in claims}
    assert values["identity_status"] == "unaccepted-candidate"
    assert values["citekey_status"] == "proposed-noncanonical"
    assert "manuscript_status" not in values
    assert values["acquisition_contract_status"] == "proposed"
