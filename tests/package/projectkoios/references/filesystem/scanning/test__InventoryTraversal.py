from __future__ import annotations

from pathlib import Path, PurePosixPath

from projectkoios.references.filesystem.inventory.status import (
    FilesystemIssueKind,
)
from projectkoios.references.filesystem.root.capability import AuthorizedRoot
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)


def test__inventory__retains_nonportable_issue_and_continues_traversal(
    tmp_path: Path,
) -> None:
    for name in ("zeta.pdf", "CON.pdf", "alpha.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-fixture")
    root = AuthorizedRoot.existing(
        tmp_path,
        label="inventory root",
        root_alias="inventory-root",
        storage_class=RootStorageClass.LOCAL,
    )

    inventory = root.inventory_files(
        suffix=".pdf",
        recursive=False,
        max_files=10,
        max_entries=10,
        max_depth=2,
    )

    assert inventory.files == (
        PurePosixPath("alpha.pdf"),
        PurePosixPath("zeta.pdf"),
    )
    assert len(inventory.issues) == 1
    assert inventory.issues[0].relative_path is None
    assert inventory.issues[0].kind is FilesystemIssueKind.NONPORTABLE_NAME
    assert inventory.entries_seen == 3
