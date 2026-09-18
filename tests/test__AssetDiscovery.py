from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from projectkoios.references.assets import (
    AssetDiscoveryPlanner,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.models import ReferenceRecord


def _record() -> ReferenceRecord:
    return ReferenceRecord(
        citekey="padbergHoffmann2015",
        entry_type="article",
        title="A Survey of Control Structures for Reconfigurable Petri Nets",
        authors=("Julia Padberg", "Kathrin Hoffmann"),
        year="2015",
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
    assert str(tmp_path) not in plan.to_json()
    assert candidate.recommendation == "strong-candidate"


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
