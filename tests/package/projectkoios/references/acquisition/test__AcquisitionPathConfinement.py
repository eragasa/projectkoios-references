from __future__ import annotations

from pathlib import Path

import pytest
from projectkoios.references import (
    PathSafetyError,
    RootStorageClass,
)
from projectkoios.references.acquisition import create_acquisition_manifest
from projectkoios.references.assets import (
    SearchRoot,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
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


def test__acquisition__rejects_symlinked_source_component(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "example2026.pdf").write_bytes(b"%PDF-external")
    root = tmp_path / "source"
    root.mkdir()
    (root / "collection").symlink_to(outside, target_is_directory=True)
    rows = (
        {
            "proposed_citekey": "example2026",
            "root_alias": "staging",
            "relative_path": "collection/example2026.pdf",
            "rights_status": "unreviewed",
            "asset_status": "candidate",
            "identity_status": "unaccepted-candidate",
        },
    )

    with pytest.raises(PathSafetyError):
        create_acquisition_manifest(
            source_id="fixture",
            rows=rows,
            roots=(SearchRoot("staging", root, RootStorageClass.LOCAL),),
        )
