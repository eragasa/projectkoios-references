"""Create-only explicit-path publication adapter."""

from __future__ import annotations

from pathlib import Path

from projectkoios.references.filesystem.root.capability import AuthorizedRoot
from projectkoios.references.filesystem.root.preflight.probe import (
    CloudPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)


def create_path_bytes(
    path: Path,
    content: bytes,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
) -> Path:
    """Create a file through its explicitly authorized parent."""
    root = AuthorizedRoot.create(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.create_bytes(path.name, content)
