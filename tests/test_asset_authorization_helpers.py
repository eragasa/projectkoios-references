from __future__ import annotations

from projectkoios.references.assets import (
    AssetCandidate,
    AssetCandidateDisposition,
    AssetDiscoveryPlan,
    AssetDispositionKind,
    CanonicalAssetAuthorization,
)
from projectkoios.references.identity import (
    ActorAuthorityScope,
    ActorKind,
    ActorProvenance,
    IdentityDecision,
    IdentityProjection,
    ReferenceCandidate,
    replay_identity_decisions,
)


def authorize_asset(
    plan: AssetDiscoveryPlan,
    selected: AssetCandidate,
    reference_candidate: ReferenceCandidate,
) -> tuple[CanonicalAssetAuthorization, IdentityProjection]:
    actor = ActorProvenance(
        actor_id="person:synthetic-asset-reviewer",
        actor_kind=ActorKind.PERSON,
        authority_scope=ActorAuthorityScope.REFERENCE_IDENTITY_CURATOR,
        verification_record_id="actor-verification:sha256:" + "a" * 64,
        verification_method="synthetic-test-verification",
    )
    promotion = IdentityDecision.promotion(
        candidate_ids=(reference_candidate.candidate_id,),
        canonical_citekey=reference_candidate.proposed_citekey,
        actor=actor,
        evidence_ids=tuple(
            sorted(
                (
                    actor.verification_record_id,
                    reference_candidate.candidate_id,
                    *reference_candidate.source_observation_ids,
                )
            )
        ),
        rationale="Synthetic fixture identity was explicitly reviewed.",
    )
    projection = replay_identity_decisions((reference_candidate,), (promotion,))
    reference_id = projection.active_reference_ids[0]
    relevant = plan.relevant_observation_ids(
        projection.accepted_references[0].candidate_ids
    )
    dispositions = tuple(
        AssetCandidateDisposition(
            asset_observation_id=observation_id,
            disposition=(
                AssetDispositionKind.AUTHORIZED_CANONICAL_CONTENT
                if observation_id == selected.observation_id
                else AssetDispositionKind.REJECTED_IDENTITY_MISMATCH
            ),
            rationale=(
                "Synthetic bytes were explicitly selected."
                if observation_id == selected.observation_id
                else "Competing synthetic candidate was explicitly rejected."
            ),
        )
        for observation_id in relevant
    )
    return (
        CanonicalAssetAuthorization.create(
            plan=plan,
            identity_projection=projection,
            reference_id=reference_id,
            selected_asset_observation_id=selected.observation_id,
            actor=actor,
            dispositions=dispositions,
        ),
        projection,
    )
