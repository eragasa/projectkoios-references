from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from projectkoios.references.assets import (
    AssetDiscoveryPlanner,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)


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
        (SearchRoot("papers", source.parent),),
    )

    candidate = plan.candidates[0]
    assert candidate.relative_path == "padbergHoffmann2015.pdf"
    assert candidate.proposed_citekey == "padbergHoffmann2015"
    assert candidate.candidate_id == _record().candidate_id
    assert candidate.identity_status == "unaccepted-candidate"
    assert candidate.citekey_status == "proposed-noncanonical"
    assert candidate.materialized_filename.startswith(
        "padbergHoffmann2015.candidate-"
    )
    assert str(tmp_path) not in plan.to_json()
    assert candidate.recommendation == "strong-candidate"

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
    roots = (SearchRoot("papers", source_root),)
    candidate = AssetDiscoveryPlanner().scan((_record(),), roots).candidates[0]
    destination = materialize_asset(
        candidate,
        roots=roots,
        destination_directory=tmp_path / "assets",
    )
    assert destination.name == candidate.materialized_filename
    assert (
        hashlib.sha256(destination.read_bytes()).hexdigest() == candidate.sha256
    )

    source.write_bytes(b"%PDF changed")
    with pytest.raises(ValueError, match="hash changed"):
        materialize_asset(
            candidate,
            roots=roots,
            destination_directory=tmp_path / "other-assets",
        )
