from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from projectkoios.references import RootStorageClass
from projectkoios.references.assets import (
    AssetCandidateDisposition,
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    AssetDispositionKind,
    AssetHeuristicKind,
    CanonicalAssetAuthorization,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.catalog import (
    CatalogConflictError,
    CatalogSchemaError,
    ReferenceCatalog,
)
from projectkoios.references.cli import main
from projectkoios.references.identity import (
    ActorAuthorityScope,
    ActorKind,
    ActorProvenance,
    IdentityDecision,
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
    replay_identity_decisions,
)
from projectkoios.references.models import SourceAssetRecord
from test_asset_authorization_helpers import authorize_asset


def _record() -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey="padbergHoffmann2015",
        entry_type="article",
        title="A Survey of Control Structures for Reconfigurable Petri Nets",
        authors=("Julia Padberg", "Kathrin Hoffmann"),
        year="2015",
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def test__asset_planner__uses_privacy_reduced_relative_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "private" / "padbergHoffmann2015.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF fixture")

    plan = AssetDiscoveryPlanner().scan(
        (_record(),),
        (SearchRoot("papers", source.parent, RootStorageClass.LOCAL),),
    )

    candidate = plan.candidates[0]
    assert candidate.relative_path == "padbergHoffmann2015.pdf"
    assert candidate.proposed_citekey == "padbergHoffmann2015"
    assert candidate.candidate_id == _record().candidate_id
    assert candidate.identity_status == "unaccepted-candidate"
    assert candidate.citekey_status == "proposed-noncanonical"
    assert candidate.match_status == "unresolved-heuristic-observation"
    assert candidate.heuristic_observations
    assert str(tmp_path) not in plan.to_json()
    assert "strong-candidate" not in plan.to_json()

    authority_claim = plan.to_json().replace(
        "unaccepted-candidate",
        "accepted-reference",
    )
    with pytest.raises(ValueError, match="accepted identity"):
        type(plan).from_json(authority_claim)


def test__materialize_asset__checks_planned_hash_and_never_overwrites(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "padbergHoffmann2015.pdf"
    source.write_bytes(b"%PDF first")
    roots = (SearchRoot("papers", source_root, RootStorageClass.LOCAL),)
    plan = AssetDiscoveryPlanner().scan((_record(),), roots)
    candidate = plan.candidates[0]
    authorization, projection = authorize_asset(plan, candidate, _record())
    destination = materialize_asset(
        candidate,
        authorization=authorization,
        plan=plan,
        identity_projection=projection,
        expected_root_preflight=plan.root_preflights[0],
        roots=roots,
        destination_directory=tmp_path / "assets",
        destination_storage_class=RootStorageClass.LOCAL,
    )
    assert destination.name == "padbergHoffmann2015.pdf"
    assert (
        hashlib.sha256(destination.read_bytes()).hexdigest() == candidate.sha256
    )

    source.write_bytes(b"%PDF changed")
    with pytest.raises(ValueError, match="hash or size changed"):
        materialize_asset(
            candidate,
            authorization=authorization,
            plan=plan,
            identity_projection=projection,
            expected_root_preflight=plan.root_preflights[0],
            roots=roots,
            destination_directory=tmp_path / "assets",
            destination_storage_class=RootStorageClass.LOCAL,
        )
    with pytest.raises(ValueError, match="hash or size changed"):
        materialize_asset(
            candidate,
            authorization=authorization,
            plan=plan,
            identity_projection=projection,
            expected_root_preflight=plan.root_preflights[0],
            roots=roots,
            destination_directory=tmp_path / "other-assets",
            destination_storage_class=RootStorageClass.LOCAL,
        )


def test__assets_apply__validates_catalog_options_before_mutation(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "must-not-exist"
    with pytest.raises(SystemExit, match="must be supplied together"):
        main(
            [
                "assets-apply",
                str(tmp_path / "plan.json"),
                "synthetic2026",
                str(destination),
                "--plan-storage-class",
                "local",
                "--destination-storage-class",
                "local",
                "--search-root",
                f"local:papers={tmp_path}",
                "--authorization",
                str(tmp_path / "authorization.json"),
                "--authorization-storage-class",
                "local",
                "--identity-projection",
                str(tmp_path / "identity.json"),
                "--identity-projection-storage-class",
                "local",
                "--catalog",
                str(tmp_path / "catalog.sqlite3"),
            ]
        )
    assert not destination.exists()


def _catalog_backed_apply_fixture(
    tmp_path: Path,
) -> tuple[
    ReferenceCandidate,
    SourceBibliographyObservation,
    AssetDiscoveryPlan,
    CanonicalAssetAuthorization,
    object,
    Path,
]:
    entry = "@article{synthetic2026, title={Synthetic Asset}}\n"
    observation = SourceBibliographyObservation.create(
        source_id="synthetic-catalog",
        asserted_source_revision="synthetic-revision",
        source_path="references.bib",
        bibliography_bytes=entry.encode(),
        entry_index=0,
        observed_citekey="synthetic2026",
        verbatim_entry=entry,
        parser=ProducerIdentity("synthetic-parser", "1"),
    )
    candidate = ReferenceCandidate.create(
        proposed_citekey="synthetic2026",
        entry_type="article",
        title="Synthetic Asset",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("synthetic-normalizer", "1"),
    )
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "synthetic2026.pdf").write_bytes(b"%PDF catalog fixture")
    plan = AssetDiscoveryPlanner().scan(
        (candidate,),
        (SearchRoot("papers", source_root, RootStorageClass.LOCAL),),
    )
    authorization, projection = authorize_asset(
        plan, plan.candidates[0], candidate
    )
    (tmp_path / "plan.json").write_text(plan.to_json(), encoding="utf-8")
    (tmp_path / "authorization.json").write_text(
        authorization.to_json(), encoding="utf-8"
    )
    (tmp_path / "identity.json").write_text(
        projection.to_json(), encoding="utf-8"
    )
    return (
        candidate,
        observation,
        plan,
        authorization,
        projection,
        source_root,
    )


@pytest.mark.parametrize(
    ("catalog_state", "expected_error"),
    (
        ("missing-candidate", CatalogSchemaError),
        ("conflict", CatalogConflictError),
        ("tampered-schema", CatalogSchemaError),
    ),
)
def test__assets_apply__catalog_preflight_prevents_destination_mutation(
    tmp_path: Path,
    catalog_state: str,
    expected_error: type[Exception],
) -> None:
    (
        candidate,
        observation,
        plan,
        _authorization,
        _projection,
        source_root,
    ) = _catalog_backed_apply_fixture(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite3"
    catalog = ReferenceCatalog(
        catalog_path, storage_class=RootStorageClass.LOCAL
    )
    catalog.initialize()
    if catalog_state != "missing-candidate":
        catalog.import_candidates((candidate,), (observation,))
    if catalog_state == "conflict":
        asset = plan.candidates[0]
        catalog.record_source_asset(
            SourceAssetRecord(
                candidate_id=candidate.candidate_id,
                proposed_citekey=candidate.proposed_citekey,
                identity_status=candidate.lifecycle_status,
                citekey_status=candidate.citekey_status,
                sha256=asset.sha256,
                byte_size=asset.byte_size,
                root_alias="existing-assets",
                relative_path="different.pdf",
                rights_status="unreviewed",
                asset_status="conflicting-fixture",
            )
        )
    elif catalog_state == "tampered-schema":
        with sqlite3.connect(catalog_path) as connection:
            connection.execute(
                "UPDATE catalog_metadata SET value = 'tampered' "
                "WHERE key = 'schema_fingerprint'"
            )
    destination = tmp_path / "destination"
    arguments = [
        "assets-apply",
        str(tmp_path / "plan.json"),
        candidate.proposed_citekey,
        str(destination),
        "--plan-storage-class",
        "local",
        "--destination-storage-class",
        "local",
        "--search-root",
        f"local:papers={source_root}",
        "--authorization",
        str(tmp_path / "authorization.json"),
        "--authorization-storage-class",
        "local",
        "--identity-projection",
        str(tmp_path / "identity.json"),
        "--identity-projection-storage-class",
        "local",
        "--catalog",
        str(catalog_path),
        "--catalog-storage-class",
        "local",
    ]

    with pytest.raises(expected_error):
        main(arguments)
    assert not destination.exists()


@pytest.mark.parametrize("preexisting", (False, True))
def test__assets_apply__rolls_back_only_exact_new_file_on_catalog_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preexisting: bool,
) -> None:
    (
        candidate,
        observation,
        _plan,
        _authorization,
        _projection,
        source_root,
    ) = _catalog_backed_apply_fixture(tmp_path)
    catalog_path = tmp_path / "catalog.sqlite3"
    catalog = ReferenceCatalog(
        catalog_path, storage_class=RootStorageClass.LOCAL
    )
    catalog.initialize()
    catalog.import_candidates((candidate,), (observation,))

    @contextmanager
    def failing_recording(
        self: ReferenceCatalog,
        asset: SourceAssetRecord,
    ):  # type: ignore[no-untyped-def]
        del self, asset
        yield
        raise CatalogConflictError("synthetic commit failure")

    monkeypatch.setattr(
        ReferenceCatalog,
        "source_asset_recording_transaction",
        failing_recording,
    )
    destination = tmp_path / "destination"
    destination_file = destination / "synthetic2026.pdf"
    if preexisting:
        destination.mkdir()
        destination_file.write_bytes(b"%PDF catalog fixture")
    with pytest.raises(CatalogConflictError, match="commit failure"):
        main(
            [
                "assets-apply",
                str(tmp_path / "plan.json"),
                candidate.proposed_citekey,
                str(destination),
                "--plan-storage-class",
                "local",
                "--destination-storage-class",
                "local",
                "--search-root",
                f"local:papers={source_root}",
                "--authorization",
                str(tmp_path / "authorization.json"),
                "--authorization-storage-class",
                "local",
                "--identity-projection",
                str(tmp_path / "identity.json"),
                "--identity-projection-storage-class",
                "local",
                "--catalog",
                str(catalog_path),
                "--catalog-storage-class",
                "local",
            ]
        )
    assert destination_file.exists() is preexisting
    if preexisting:
        assert destination_file.read_bytes() == b"%PDF catalog fixture"


def test__exact_filename_is_only_an_unresolved_observation(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "padbergHoffmann2015.pdf").write_bytes(
        b"%PDF synthetic wrong-content fixture"
    )
    plan = AssetDiscoveryPlanner().scan(
        (_record(),),
        (SearchRoot("papers", source_root, RootStorageClass.LOCAL),),
    )

    candidate = plan.candidates[0]
    assert candidate.match_status == "unresolved-heuristic-observation"
    assert tuple(item.kind for item in candidate.heuristic_observations) == (
        AssetHeuristicKind.EXACT_PROPOSED_CITEKEY_FILENAME,
    )
    assert "accepted" not in candidate.match_status
    assert not hasattr(candidate, "score")
    assert not hasattr(candidate, "recommendation")


def test__asset_plan_schema_3_fails_closed() -> None:
    legacy = """{
  "schema_version": 3,
  "coverage_status": "complete",
  "effective_limits": {},
  "effective_limits_id": "legacy",
  "root_preflights": [],
  "file_observations": [],
  "candidates": []
}
"""
    with pytest.raises(ValueError, match="legacy plans"):
        AssetDiscoveryPlan.from_json(legacy)


def test__canonical_authorization_dispositions_retain_all_ambiguity(
    tmp_path: Path,
) -> None:
    alpha = ReferenceCandidate.create(
        proposed_citekey="alpha",
        entry_type="article",
        title="Alpha Work",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "1" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )
    beta = ReferenceCandidate.create(
        proposed_citekey="beta",
        entry_type="article",
        title="Beta Work",
        authors=("B. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "2" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "alpha-beta.pdf").write_bytes(b"%PDF selected")
    (source_root / "beta-alternate.pdf").write_bytes(b"%PDF alternate")
    plan = AssetDiscoveryPlanner().scan(
        (alpha, beta),
        (SearchRoot("papers", source_root, RootStorageClass.LOCAL),),
    )
    selected = next(
        item
        for item in plan.candidates
        if item.candidate_id == alpha.candidate_id
        and item.relative_path == "alpha-beta.pdf"
    )
    actor = ActorProvenance(
        actor_id="person:asset-curator",
        actor_kind=ActorKind.PERSON,
        authority_scope=ActorAuthorityScope.REFERENCE_IDENTITY_CURATOR,
        verification_record_id="actor-verification:sha256:" + "b" * 64,
        verification_method="synthetic verification",
    )
    promotion = IdentityDecision.promotion(
        candidate_ids=(alpha.candidate_id,),
        canonical_citekey="canonical-alpha",
        actor=actor,
        evidence_ids=tuple(
            sorted(
                (
                    actor.verification_record_id,
                    alpha.candidate_id,
                    *alpha.source_observation_ids,
                )
            )
        ),
        rationale="The synthetic alpha bibliography identity was reviewed.",
    )
    projection = replay_identity_decisions((alpha, beta), (promotion,))
    relevant = plan.relevant_observation_ids((alpha.candidate_id,))
    dispositions = tuple(
        AssetCandidateDisposition(
            asset_observation_id=observation_id,
            disposition=(
                AssetDispositionKind.AUTHORIZED_CANONICAL_CONTENT
                if observation_id == selected.observation_id
                else (
                    AssetDispositionKind.RETAINED_COMPETING_CANDIDATE
                    if plan.candidate_by_observation_id(observation_id).sha256
                    == selected.sha256
                    else AssetDispositionKind.REJECTED_IDENTITY_MISMATCH
                )
            ),
            rationale=(
                "Selected after exact synthetic byte review."
                if observation_id == selected.observation_id
                else "Retained or rejected after explicit synthetic review."
            ),
        )
        for observation_id in relevant
    )
    authorization = CanonicalAssetAuthorization.create(
        plan=plan,
        identity_projection=projection,
        reference_id=projection.active_reference_ids[0],
        selected_asset_observation_id=selected.observation_id,
        actor=actor,
        dispositions=dispositions,
    )

    assert plan.ambiguity_status(alpha.candidate_id) == (
        "unresolved-competing-candidates-and-source-versions"
    )
    assert len(relevant) == 3
    beta_alternate = next(
        item
        for item in plan.candidates
        if item.relative_path == "beta-alternate.pdf"
    )
    assert beta_alternate.observation_id in relevant
    assert {
        item.asset_observation_id for item in authorization.dispositions
    } == set(relevant)
    assert all(item.rationale for item in authorization.dispositions)
    assert (
        CanonicalAssetAuthorization.from_json(authorization.to_json())
        == authorization
    )
    with pytest.raises(ValueError, match="every competing candidate"):
        CanonicalAssetAuthorization.create(
            plan=plan,
            identity_projection=projection,
            reference_id=projection.active_reference_ids[0],
            selected_asset_observation_id=selected.observation_id,
            actor=actor,
            dispositions=(
                next(
                    item
                    for item in dispositions
                    if item.asset_observation_id == selected.observation_id
                ),
            ),
        )
