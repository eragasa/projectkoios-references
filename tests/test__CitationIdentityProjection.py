from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pytest
from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.citation_identity import (
    CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES,
    CitationIdentityProjectionItem,
    CitationIdentityProjectionRequest,
    CitationIdentityProjectionResult,
    CitationIdentityProjectionStatus,
    CitationIdentityProjector,
)
from projectkoios.references.identity import (
    ActorAuthorityScope,
    ActorKind,
    ActorProvenance,
    IdentityDecision,
    IdentityProjection,
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
    replay_identity_decisions,
)


class _EncodeTrap(str):
    def encode(
        self,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> bytes:
        del encoding, errors
        raise AssertionError(
            "overlength identity must be rejected before encode"
        )


def _observation(citekey: str) -> SourceBibliographyObservation:
    entry = f"@article{{{citekey}}}\n"
    return SourceBibliographyObservation.create(
        source_id="citation-projection-test",
        asserted_source_revision="test-revision",
        source_path="references.bib",
        bibliography_bytes=entry.encode(),
        entry_index=0,
        observed_citekey=citekey,
        verbatim_entry=entry,
        parser=ProducerIdentity("test-parser", "1"),
    )


def _candidate(
    citekey: str,
    observation: SourceBibliographyObservation,
) -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey=citekey,
        entry_type="article",
        title=f"Candidate {citekey}",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("test-normalizer", "1"),
    )


def _actor() -> ActorProvenance:
    return ActorProvenance(
        actor_id="person:citation-projection-reviewer",
        actor_kind=ActorKind.PERSON,
        authority_scope=ActorAuthorityScope.REFERENCE_IDENTITY_CURATOR,
        verification_record_id="actor-verification:sha256:" + "a" * 64,
        verification_method="test-authentication-record",
    )


def _evidence(actor: ActorProvenance, *identities: str) -> tuple[str, ...]:
    return tuple(sorted((*identities, actor.verification_record_id)))


def _merged_projection() -> tuple[
    IdentityProjection,
    tuple[ReferenceCandidate, ...],
    tuple[str, ...],
    str,
]:
    observations = (_observation("firstDraft"), _observation("secondDraft"))
    candidates = tuple(
        sorted(
            (
                _candidate("firstDraft", observations[0]),
                _candidate("secondDraft", observations[1]),
            ),
            key=lambda item: item.candidate_id,
        )
    )
    actor = _actor()
    promotions = tuple(
        IdentityDecision.promotion(
            candidate_ids=(candidate.candidate_id,),
            canonical_citekey=f"accepted{index}",
            actor=actor,
            evidence_ids=_evidence(
                actor,
                candidate.candidate_id,
                candidate.source_observation_ids[0],
            ),
            rationale=f"Accept candidate {index} for projection tests.",
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    promoted = replay_identity_decisions(candidates, promotions)
    source_ids = promoted.active_reference_ids
    candidate_ids = tuple(item.candidate_id for item in candidates)
    merge = IdentityDecision.merge(
        input_reference_ids=source_ids,
        candidate_ids=candidate_ids,
        canonical_citekey="mergedCanonical",
        actor=actor,
        evidence_ids=_evidence(
            actor,
            *source_ids,
            *candidate_ids,
            *(decision.decision_id for decision in promotions),
        ),
        rationale="Merge the two accepted identities for projection tests.",
        supersedes_decision_ids=tuple(
            sorted(decision.decision_id for decision in promotions)
        ),
    )
    projection = replay_identity_decisions(candidates, (*promotions, merge))
    return (
        projection,
        candidates,
        source_ids,
        projection.active_reference_ids[0],
    )


def _request(
    projection: IdentityProjection,
    *identity_ids: str,
) -> CitationIdentityProjectionRequest:
    return CitationIdentityProjectionRequest(
        projection=projection,
        identity_ids=tuple(sorted(identity_ids)),
    )


def test__projector__distinguishes_identity_states_without_promotion() -> None:
    projection, candidates, source_ids, active_id = _merged_projection()
    missing_id = "opaque-bibliographic-identity:missing"
    request = _request(
        projection,
        active_id,
        candidates[0].candidate_id,
        missing_id,
        source_ids[0],
    )

    result = CitationIdentityProjector().project(request=request)
    by_id = {item.requested_identity_id: item for item in result.items}

    active = by_id[active_id]
    assert active.status is (
        CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL
    )
    assert active.canonical_citekey == "mergedCanonical"
    assert active.proposed_citekey is None

    candidate = by_id[candidates[0].candidate_id]
    assert candidate.status is (
        CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
    )
    assert candidate.proposed_citekey == candidates[0].proposed_citekey
    assert candidate.canonical_citekey is None
    assert candidate.reference_id is None

    superseded = by_id[source_ids[0]]
    assert superseded.status is (
        CitationIdentityProjectionStatus.INACTIVE_SUPERSEDED
    )
    assert superseded.successor_reference_ids == (active_id,)
    assert superseded.canonical_citekey is None

    assert by_id[missing_id].status is (
        CitationIdentityProjectionStatus.UNRESOLVED
    )
    assert result.projection_id == projection.projection_id
    assert tuple(item.requested_identity_id for item in result.items) == (
        request.identity_ids
    )


def test__projector__uses_base_roles_one_logic_path_and_stable_ids() -> None:
    projection, candidates, _, active_id = _merged_projection()
    request = _request(projection, active_id, candidates[0].candidate_id)
    projector = CitationIdentityProjector()

    projected = projector.project(request=request)

    assert issubclass(
        CitationIdentityProjectionRequest,
        DataObjectActionRequest,
    )
    assert issubclass(CitationIdentityProjectionItem, DataObjectModel)
    assert issubclass(
        CitationIdentityProjectionResult,
        DataObjectActionResult,
    )
    assert issubclass(CitationIdentityProjector, DataObjectActionizer)
    assert projector.action(request=request) == projected
    assert projected == CitationIdentityProjector().project(
        request=_request(projection, active_id, candidates[0].candidate_id)
    )
    assert projected.request is request
    assert projected.result_id.startswith(
        "citation-identity-projection-result:sha256:"
    )
    assert all(
        item.item_id.startswith("citation-identity-projection-item:sha256:")
        for item in projected.items
    )
    with pytest.raises(FrozenInstanceError):
        request.identity_ids = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        projected.items = ()  # type: ignore[misc]


def test__reserved_no_active_citekey_status__enforces_item_invariants() -> None:
    projection, _, _, active_id = _merged_projection()

    item = CitationIdentityProjectionItem(
        requested_identity_id=active_id,
        projection_id=projection.projection_id,
        status=(
            CitationIdentityProjectionStatus.ACCEPTED_WITHOUT_ACTIVE_CITEKEY
        ),
        reference_id=active_id,
    )

    assert item.canonical_citekey is None
    assert item.proposed_citekey is None
    with pytest.raises(ValueError, match="non-key outcome fields"):
        CitationIdentityProjectionItem(
            requested_identity_id=active_id,
            projection_id=projection.projection_id,
            status=(
                CitationIdentityProjectionStatus.ACCEPTED_WITHOUT_ACTIVE_CITEKEY
            ),
            reference_id=active_id,
            canonical_citekey="notActive",
        )


def test__request__rejects_duplicates_order_bounds_and_malformed_ids() -> None:
    projection, candidates, _, active_id = _merged_projection()
    candidate_id = candidates[0].candidate_id

    with pytest.raises(ValueError, match="duplicates"):
        CitationIdentityProjectionRequest(
            projection=projection,
            identity_ids=(candidate_id, candidate_id),
        )
    with pytest.raises(ValueError, match="canonical sorted order"):
        CitationIdentityProjectionRequest(
            projection=projection,
            identity_ids=(candidate_id, active_id),
        )
    with pytest.raises(ValueError, match="non-empty"):
        CitationIdentityProjectionRequest(
            projection=projection,
            identity_ids=(),
        )
    with pytest.raises(ValueError, match="item limit"):
        CitationIdentityProjectionRequest(
            projection=projection,
            identity_ids=tuple(
                f"opaque:{index:04d}"
                for index in range(
                    CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES + 1
                )
            ),
        )
    for malformed in (" leading-space", "control\x7f", "\ud800"):
        with pytest.raises(ValueError, match="malformed"):
            CitationIdentityProjectionRequest(
                projection=projection,
                identity_ids=(malformed,),
            )
    with pytest.raises(ValueError, match="malformed"):
        CitationIdentityProjectionRequest(
            projection=projection,
            identity_ids=(_EncodeTrap("x" * 513),),
        )
    with pytest.raises(TypeError, match="string tuple"):
        CitationIdentityProjectionRequest(
            projection=projection,
            identity_ids=[candidate_id],  # type: ignore[arg-type]
        )


def test__request__rejects_forged_projection_with_retained_identity() -> None:
    projection, _, _, active_id = _merged_projection()
    forged = copy.copy(projection)
    active_binding = next(
        binding for binding in projection.name_history if binding.active
    )
    forged_binding = copy.copy(active_binding)
    forged_binding.__dict__["canonical_citekey"] = "forgedKey"
    forged.__dict__["name_history"] = tuple(
        forged_binding if binding is active_binding else binding
        for binding in projection.name_history
    )

    assert forged.projection_id == projection.projection_id
    with pytest.raises(ValueError, match="does not match replay"):
        _request(forged, active_id)


def test__item_and_result__reject_authority_and_correlation_ambiguity() -> None:
    projection, candidates, _, active_id = _merged_projection()
    candidate_id = candidates[0].candidate_id
    with pytest.raises(ValueError, match="candidate outcome fields"):
        CitationIdentityProjectionItem(
            requested_identity_id=candidate_id,
            projection_id=projection.projection_id,
            status=(
                CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
            ),
            proposed_citekey=candidates[0].proposed_citekey,
            canonical_citekey="mustNotPromote",
        )

    request = _request(projection, active_id, candidate_id)
    projected = CitationIdentityProjector().project(request=request)
    with pytest.raises(ValueError, match="correlation"):
        CitationIdentityProjectionResult(
            request=request,
            items=tuple(reversed(projected.items)),
        )
