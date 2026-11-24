"""Explicit-path adapters over descriptor-confined authorized roots."""

from __future__ import annotations

from pathlib import Path

from projectkoios.references.filesystem.root.capability import AuthorizedRoot
from projectkoios.references.filesystem.root.preflight.probe import (
    RootPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)

_DEFAULT_READ_MAX_BYTES = 50_000_000


def read_path_bytes(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: RootPlaceholderProbe | None = None,
    max_bytes: int = _DEFAULT_READ_MAX_BYTES,
) -> bytes:
    """Read an explicitly classified file through its authorized parent."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.read_bytes(path.name, max_bytes=max_bytes)


def read_path_text(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: RootPlaceholderProbe | None = None,
    encoding: str = "utf-8",
    max_bytes: int = _DEFAULT_READ_MAX_BYTES,
) -> str:
    """Read an explicitly classified text file without following symlinks."""
    return read_path_bytes(
        path,
        label=label,
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
        max_bytes=max_bytes,
    ).decode(encoding)
