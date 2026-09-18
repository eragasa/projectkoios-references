from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import projectkoios.references as public_api
import pytest
from projectkoios.references.identity import (
    AcceptedReference,
    ActorAuthorityScope,
    ActorKind,
    ActorProvenance,
    CanonicalPlan,
    IdentityDecision,
    IdentityProjection,
    IdentityRecordError,
    LegacySeedMapping,
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
    replay_identity_decisions,
)


def _observation(citekey: str, entry: str) -> SourceBibliographyObservation:
    bibliography = entry.encode("utf-8")
    return SourceBibliographyObservation.create(
        source_id="test-bibliography",
        asserted_source_revision="asserted-revision",
        source_path="references.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey=citekey,
        verbatim_entry=entry,
        parser=ProducerIdentity("test-parser", "1"),
    )


def _candidate(
    citekey: str,
    title: str,
    observation: SourceBibliographyObservation,
) -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey=citekey,
        entry_type="article",
        title=title,
        authors=("A. Author",),
        year="2026",
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("test-normalizer", "1"),
    )


def _actor() -> ActorProvenance:
    return ActorProvenance(
        actor_id="person:reviewer",
        actor_kind=ActorKind.PERSON,
        authority_scope=ActorAuthorityScope.REFERENCE_IDENTITY_CURATOR,
        verification_record_id=("actor-verification:sha256:" + "a" * 64),
        verification_method="test-authentication-record",
    )


def _evidence(actor: ActorProvenance, *identities: str) -> tuple[str, ...]:
    return tuple(sorted((*identities, actor.verification_record_id)))


def test__replay_derived_authority_cannot_be_constructed_directly() -> None:
    assert not hasattr(public_api, "AcceptedReference")
    assert not hasattr(public_api, "CanonicalNameBinding")
    assert not hasattr(public_api, "ReferenceAliasBinding")
    assert not hasattr(public_api, "ReferenceSupersession")

    with pytest.raises(IdentityRecordError, match="only be created by"):
        AcceptedReference(
            reference_id="canonical-reference:sha256:" + "1" * 64,
            candidate_ids=("reference-candidate:sha256:" + "2" * 64,),
            creating_decision_id="identity-decision:sha256:" + "3" * 64,
        )

    with pytest.raises(IdentityRecordError, match="only be created by"):
        IdentityProjection(
            schema_version=1,
            authority_kind="canonical-identity-projection",
            candidates=(),
            decisions=(),
            accepted_references=(),
            name_history=(),
            alias_history=(),
            supersessions=(),
            active_reference_ids=(),
            projection_id="identity-projection:sha256:" + "4" * 64,
        )


def test__observations_candidates_and_legacy_seeds_are_not_authority() -> None:
    entry = "@article{LegacyKey,\n  title = {  Exact Source  },\n}\n"
    observation = _observation("LegacyKey", entry)
    candidate = _candidate("LegacyKey", "Exact Source", observation)
    mapping = LegacySeedMapping.from_candidate(candidate)

    assert observation.verbatim_entry == entry
    assert observation.bibliography_byte_size == len(entry.encode("utf-8"))
    assert candidate.authority_kind == "reference-candidate"
    assert candidate.lifecycle_status == "unaccepted-candidate"
    assert candidate.citekey_status == "proposed-noncanonical"
    assert mapping.canonical_authority == "not-established"
    assert candidate.candidate_id != observation.observation_id
    assert replay_identity_decisions((candidate,), ()).accepted_references == ()

    assert (
        SourceBibliographyObservation.from_json(observation.to_json())
        == observation
    )
    assert ReferenceCandidate.from_json(candidate.to_json()) == candidate
    assert LegacySeedMapping.from_json(mapping.to_json()) == mapping

    with pytest.raises(IdentityRecordError, match="not present"):
        SourceBibliographyObservation.create(
            source_id="test-bibliography",
            asserted_source_revision=None,
            source_path="references.bib",
            bibliography_bytes=b"@article{different}\n",
            entry_index=0,
            observed_citekey="LegacyKey",
            verbatim_entry=entry,
            parser=ProducerIdentity("test-parser", "1"),
        )


def test__normalization_is_deterministic_but_does_not_merge_sources() -> None:
    first_observation = _observation(
        "firstKey",
        "@article{firstKey, title={Same Work}}\n",
    )
    second_observation = _observation(
        "secondKey",
        "@article{secondKey, title={Same Work}}\n",
    )
    first = _candidate("firstKey", "Same Work", first_observation)
    repeated = _candidate("firstKey", "Same Work", first_observation)
    second = _candidate("secondKey", "Same Work", second_observation)

    assert first == repeated
    assert first.candidate_id == repeated.candidate_id
    assert first.candidate_id != second.candidate_id
    projection = replay_identity_decisions(
        tuple(sorted((first, second), key=lambda item: item.candidate_id)),
        (),
    )
    assert projection.active_reference_ids == ()


def test__promotion_requires_actor_scope_and_evidence_and_round_trips() -> None:
    observation = _observation("candidateKey", "@article{candidateKey}\n")
    candidate = _candidate("candidateKey", "Candidate", observation)
    actor = _actor()
    decision = IdentityDecision.promotion(
        canonical_citekey="acceptedKey",
        candidate_ids=(candidate.candidate_id,),
        actor=actor,
        evidence_ids=_evidence(
            actor,
            candidate.candidate_id,
            observation.observation_id,
        ),
        rationale="Reviewed source evidence and accepted this identity.",
    )

    projection = replay_identity_decisions((candidate,), (decision,))

    assert len(projection.accepted_references) == 1
    assert projection.active_reference_ids == (
        projection.accepted_references[0].reference_id,
    )
    assert projection.name_history[0].canonical_citekey == "acceptedKey"
    assert projection.name_history[0].active is True
    assert decision.actor.verification_record_id in decision.evidence_ids
    assert IdentityProjection.from_json(projection.to_json()) == projection

    with pytest.raises(FrozenInstanceError):
        decision.evidence_ids = ()  # type: ignore[misc]
    with pytest.raises(IdentityRecordError, match="verification"):
        IdentityDecision.promotion(
            canonical_citekey=decision.outputs[0].canonical_citekey,
            candidate_ids=decision.outputs[0].candidate_ids,
            actor=actor,
            evidence_ids=(
                candidate.candidate_id,
                observation.observation_id,
            ),
            rationale="Missing actor verification.",
        )

    missing_source = IdentityDecision.promotion(
        canonical_citekey="missingSource",
        candidate_ids=(candidate.candidate_id,),
        actor=actor,
        evidence_ids=_evidence(actor, candidate.candidate_id),
        rationale="This decision intentionally omits source evidence.",
    )
    with pytest.raises(IdentityRecordError, match="source observation"):
        replay_identity_decisions((candidate,), (missing_source,))


def test__merge_alias_migration_and_split_are_replayable_history() -> None:
    observations = (
        _observation("one", "@article{one}\n"),
        _observation("two", "@article{two}\n"),
    )
    candidates = tuple(
        sorted(
            (
                _candidate("one", "One", observations[0]),
                _candidate("two", "Two", observations[1]),
            ),
            key=lambda item: item.candidate_id,
        )
    )
    actor = _actor()
    promotions = tuple(
        IdentityDecision.promotion(
            canonical_citekey=f"accepted-{index}",
            candidate_ids=(candidate.candidate_id,),
            actor=actor,
            evidence_ids=_evidence(
                actor,
                candidate.candidate_id,
                candidate.source_observation_ids[0],
            ),
            rationale=f"Accept candidate {index} after review.",
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    promoted = replay_identity_decisions(candidates, promotions)
    source_ids = promoted.active_reference_ids
    merged_candidates = tuple(
        sorted(candidate.candidate_id for candidate in candidates)
    )
    merge = IdentityDecision.merge(
        input_reference_ids=source_ids,
        canonical_citekey="merged",
        candidate_ids=merged_candidates,
        actor=actor,
        evidence_ids=_evidence(
            actor,
            *source_ids,
            *merged_candidates,
            *(decision.decision_id for decision in promotions),
        ),
        rationale="The two accepted records describe one work.",
        supersedes_decision_ids=tuple(
            sorted(decision.decision_id for decision in promotions)
        ),
    )
    merged = replay_identity_decisions(candidates, (*promotions, merge))
    merged_id = merged.active_reference_ids[0]
    alias = IdentityDecision.alias(
        target_reference_id=merged_id,
        alias_citekey="historical-name",
        actor=actor,
        evidence_ids=_evidence(actor, merged_id),
        rationale="Preserve the documented historical spelling.",
    )
    aliased = replay_identity_decisions(
        candidates,
        (*promotions, merge, alias),
    )
    historical_alias_id = aliased.alias_history[0].alias_id
    migration = IdentityDecision.migrate_citekey(
        target_reference_id=merged_id,
        prior_citekey="merged",
        new_citekey="renamed",
        candidate_ids=merged_candidates,
        actor=actor,
        evidence_ids=_evidence(
            actor,
            merged_id,
            *merged_candidates,
            merge.decision_id,
        ),
        rationale="Adopt the reviewed citekey while preserving the old name.",
        supersedes_decision_id=merge.decision_id,
    )
    split = IdentityDecision.split(
        input_reference_id=merged_id,
        outputs=(
            CanonicalPlan("split-one", (candidates[0].candidate_id,)),
            CanonicalPlan("split-two", (candidates[1].candidate_id,)),
        ),
        actor=actor,
        evidence_ids=_evidence(
            actor,
            merged_id,
            *merged_candidates,
            migration.decision_id,
        ),
        rationale="New evidence distinguishes two works.",
        supersedes_decision_id=migration.decision_id,
    )

    decisions = (*promotions, merge, alias, migration, split)
    projection = replay_identity_decisions(candidates, decisions)
    replayed = IdentityProjection.from_json(projection.to_json())

    assert replayed == projection
    assert len(projection.active_reference_ids) == 2
    assert len(projection.supersessions) == 3
    assert any(
        item.canonical_citekey == "renamed" and not item.active
        for item in projection.name_history
    )
    assert {item.alias_citekey for item in projection.alias_history} == {
        "historical-name",
        "merged",
    }
    assert not any(item.active for item in projection.alias_history)
    assert (
        next(
            item.alias_id
            for item in projection.alias_history
            if item.alias_citekey == "historical-name"
        )
        == historical_alias_id
    )


def test__replay_fails_closed_for_collisions_and_tampering() -> None:
    observation = _observation("candidate", "@article{candidate}\n")
    candidate = _candidate("candidate", "Candidate", observation)
    actor = _actor()
    first = IdentityDecision.promotion(
        canonical_citekey="same-key",
        candidate_ids=(candidate.candidate_id,),
        actor=actor,
        evidence_ids=_evidence(
            actor,
            candidate.candidate_id,
            observation.observation_id,
        ),
        rationale="First reviewed promotion.",
    )
    projection = replay_identity_decisions((candidate,), (first,))

    tampered = json.loads(projection.to_json())
    tampered["name_history"][0]["canonical_citekey"] = "changed"
    with pytest.raises(IdentityRecordError):
        IdentityProjection.from_json(json.dumps(tampered))

    second_observation = _observation("other", "@article{other}\n")
    second_candidate = _candidate("other", "Other", second_observation)
    second = IdentityDecision.promotion(
        canonical_citekey="same-key",
        candidate_ids=(second_candidate.candidate_id,),
        actor=actor,
        evidence_ids=_evidence(
            actor,
            second_candidate.candidate_id,
            second_observation.observation_id,
        ),
        rationale="Second reviewed promotion with a conflicting name.",
    )
    candidates = tuple(
        sorted(
            (candidate, second_candidate), key=lambda item: item.candidate_id
        )
    )
    with pytest.raises(IdentityRecordError, match="already active"):
        replay_identity_decisions(candidates, (first, second))
