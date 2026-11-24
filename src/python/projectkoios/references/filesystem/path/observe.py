"""Explicit-path adapters over descriptor-confined authorized roots."""

from __future__ import annotations

from pathlib import Path

from projectkoios.references.filesystem.observation.file import FileObservation
from projectkoios.references.filesystem.root.capability import AuthorizedRoot
from projectkoios.references.filesystem.root.preflight.probe import (
    CloudPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)

_DEFAULT_READ_MAX_BYTES = 50_000_000


def observe_path_file(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    max_bytes: int,
    prefix_bytes: int = 0,
) -> FileObservation:
    """Observe an explicitly classified file without loading it into memory."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.observe_file(
        path.name,
        max_bytes=max_bytes,
        prefix_bytes=prefix_bytes,
    )
