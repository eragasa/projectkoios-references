from __future__ import annotations

from pathlib import Path

import pytest
from projectkoios.references import (
    PathSafetyError,
    RootStorageClass,
)
from projectkoios.references.assets import (
    AssetCandidate,
    AssetCandidateDisposition,
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    AssetDispositionKind,
    CanonicalAssetAuthorization,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.identity import (
    ActorAuthorityScope,
    ActorKind,
    ActorProvenance,
    IdentityDecision,
    IdentityProjection,
    ProducerIdentity,
    ReferenceCandidate,
    replay_identity_decisions,
)


def _authorize_asset(
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
            reference_id=projection.active_reference_ids[0],
            selected_asset_observation_id=selected.observation_id,
            actor=actor,
            dispositions=dispositions,
        ),
        projection,
    )


def _record() -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey="example2026",
        entry_type="article",
        title="Example",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def test__asset_scan__rejects_symlink_file_and_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "example2026.pdf"
    external.write_bytes(b"%PDF-external")

    file_root = tmp_path / "file-root"
    file_root.mkdir()
    (file_root / "example2026.pdf").symlink_to(external)
    with pytest.raises(PathSafetyError, match="symlink"):
        AssetDiscoveryPlanner().scan(
            (_record(),),
            (SearchRoot("papers", file_root, RootStorageClass.LOCAL),),
        )

    directory_root = tmp_path / "directory-root"
    directory_root.mkdir()
    (directory_root / "linked").symlink_to(
        outside,
        target_is_directory=True,
    )
    with pytest.raises(PathSafetyError, match="symlink"):
        AssetDiscoveryPlanner().scan(
            (_record(),),
            (SearchRoot("papers", directory_root, RootStorageClass.LOCAL),),
        )


def test__materialize_asset__rechecks_source_and_destination_symlinks(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "example2026.pdf"
    content = b"%PDF-safe"
    source.write_bytes(content)
    roots = (SearchRoot("papers", source_root, RootStorageClass.LOCAL),)
    plan = AssetDiscoveryPlanner().scan((_record(),), roots)
    candidate = plan.candidates[0]
    authorization, projection = _authorize_asset(plan, candidate, _record())

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(content)
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(PathSafetyError):
        materialize_asset(
            candidate,
            authorization=authorization,
            plan=plan,
            identity_projection=projection,
            expected_root_preflight=plan.root_preflights[0],
            roots=roots,
            destination_directory=tmp_path / "assets-a",
            destination_storage_class=RootStorageClass.LOCAL,
        )

    source.unlink()
    source.write_bytes(content)
    destination = tmp_path / "assets-b"
    destination.mkdir()
    protected = tmp_path / "protected.pdf"
    protected.write_bytes(b"do not replace")
    (destination / "example2026.pdf").symlink_to(protected)
    with pytest.raises(PathSafetyError):
        materialize_asset(
            candidate,
            authorization=authorization,
            plan=plan,
            identity_projection=projection,
            expected_root_preflight=plan.root_preflights[0],
            roots=roots,
            destination_directory=destination,
            destination_storage_class=RootStorageClass.LOCAL,
        )
    assert protected.read_bytes() == b"do not replace"
