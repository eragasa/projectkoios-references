from __future__ import annotations

import os
from pathlib import Path

import pytest
from projectkoios.references.filesystem.descriptor.error import (
    FilesystemDescriptorError,
)
from projectkoios.references.filesystem.observation.error import (
    FilesystemObservationError,
)
from projectkoios.references.filesystem.root.capability import AuthorizedRoot
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)
from projectkoios.references.filesystem.scanning.error import (
    FilesystemScanningError,
)


def _root(path: Path) -> AuthorizedRoot:
    return AuthorizedRoot.existing(
        path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )


def test__filesystem_operations__raise_owner_specific_security_errors(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = _root(root_path)

    root.create_bytes("target.pdf", b"payload")
    with pytest.raises(FileExistsError):
        root.create_bytes("target.pdf", b"replacement")

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    os.symlink(outside, root_path / "linked.pdf")
    with pytest.raises(FilesystemObservationError, match="symlink"):
        root.state("linked.pdf")

    (root_path / "child").mkdir()
    with pytest.raises(FilesystemScanningError, match="directory"):
        root.iter_files(
            suffix=".pdf",
            recursive=False,
            reject_directories=True,
        )

    authorized = tmp_path / "authorized"
    root_path.rename(authorized)
    root_path.mkdir()
    with pytest.raises(FilesystemDescriptorError, match="changed"):
        root.state("missing.pdf")
