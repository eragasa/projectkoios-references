from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import projectkoios.references as references_api
import pytest
from projectkoios.references.filesystem.observation.capability import (
    RootObservation,
)
from projectkoios.references.filesystem.publication.capability import (
    RootPublication,
)
from projectkoios.references.filesystem.root.capability import AuthorizedRoot
from projectkoios.references.filesystem.root.identity import (
    AuthorizedRootIdentity,
)
from projectkoios.references.filesystem.root.preflight.evidence import (
    RootPreflightEvidence,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)
from projectkoios.references.filesystem.scanning.capability import RootScanning


def test__root_identity__contains_no_live_probe_or_operation_capability() -> (
    None
):
    identity = AuthorizedRootIdentity(
        path=Path("/bounded/root"),
        label="bounded root",
        device=1,
        inode=2,
        preflight_evidence=RootPreflightEvidence(
            root_alias="bounded-root",
            storage_class=RootStorageClass.LOCAL,
            probe_id="local-root-no-cloud-probe-v1",
            probe_support=None,
        ),
    )

    assert {item.name for item in fields(identity)} == {
        "path",
        "label",
        "device",
        "inode",
        "preflight_evidence",
        "mount_id",
    }
    assert not hasattr(identity, "placeholder_probe")
    assert not hasattr(identity, "read_bytes")
    assert not hasattr(identity, "write_bytes")


def test__authorized_root__composes_narrow_operations_without_inheritance(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )

    assert AuthorizedRoot.__bases__ == (object,)
    assert isinstance(root.observation, RootObservation)
    assert isinstance(root.scanning, RootScanning)
    assert isinstance(root.publication, RootPublication)
    assert root.observation is not root.scanning
    assert root.scanning is not root.publication


def test__authorized_root__cannot_rebind_identity_operations_or_probe(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    (first_path / "value.txt").write_text("first", encoding="utf-8")
    (second_path / "value.txt").write_text("second", encoding="utf-8")
    first = AuthorizedRoot.existing(
        first_path,
        label="first root",
        root_alias="first-root",
        storage_class=RootStorageClass.LOCAL,
    )
    second = AuthorizedRoot.existing(
        second_path,
        label="second root",
        root_alias="second-root",
        storage_class=RootStorageClass.LOCAL,
    )

    with pytest.raises(FrozenInstanceError):
        first.identity = second.identity  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.observation = second.observation  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.scanning = second.scanning  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.publication = second.publication  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.placeholder_probe = second.placeholder_probe  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.observation.placeholder_probe = (  # type: ignore[misc]
            second.placeholder_probe
        )
    with pytest.raises(FrozenInstanceError):
        first.observation._descriptor = (  # type: ignore[misc]
            second.observation._descriptor
        )

    assert first.path == first_path
    assert first.read_text("value.txt") == "first"


def test__removed_facades__are_not_public_api() -> None:
    for name in (
        "AuthorizedRoot",
        "PathSafetyError",
        "PathLimitError",
        "RootStorageClass",
        "validate_citekey",
        "validate_relative_path",
    ):
        assert not hasattr(references_api, name)
