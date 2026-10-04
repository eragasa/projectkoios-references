"""Explicit-path adapters over descriptor-confined authorized roots."""

from __future__ import annotations

import warnings
from pathlib import Path

from projectkoios.references.path_safety import (
    errors,
    inventory,
    preflight,
)
from projectkoios.references.path_safety import (
    root as authorized_root,
)

_DEFAULT_READ_MAX_BYTES = 50_000_000


def read_path_bytes(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: preflight.RootStorageClass,
    placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
    max_bytes: int = _DEFAULT_READ_MAX_BYTES,
) -> bytes:
    """Read an explicitly classified file through its authorized parent."""
    root = authorized_root.AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.read_bytes(path.name, max_bytes=max_bytes)


def observe_path_file(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: preflight.RootStorageClass,
    placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
    max_bytes: int,
    prefix_bytes: int = 0,
) -> inventory.FileObservation:
    """Observe an explicitly classified file without loading it into memory."""
    root = authorized_root.AuthorizedRoot.existing(
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


def read_path_text(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: preflight.RootStorageClass,
    placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
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


def write_path_bytes(
    path: Path,
    content: bytes,
    *,
    label: str,
    root_alias: str,
    storage_class: preflight.RootStorageClass,
    placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
    replace: bool,
) -> Path:
    """Write through an explicitly classified authorized parent."""
    root = authorized_root.AuthorizedRoot.create(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.write_bytes(path.name, content, replace=replace)


def assert_safe_explicit_path(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: preflight.RootStorageClass,
    placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
) -> Path:
    """Return a metadata-checked path, not durable access authorization.

    Deprecated because a pathname can be replaced after this function returns.
    Callers requiring authorization must use descriptor-confined operations.
    """
    warnings.warn(
        "assert_safe_explicit_path is metadata-only and deprecated",
        DeprecationWarning,
        stacklevel=2,
    )
    root = authorized_root.AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    state = root.state(path.name)
    if state == "regular":
        root.require_readable_file(path.name)
    if state not in {"missing", "regular"}:
        raise errors.PathSafetyError(
            f"{label} must be a regular file or missing"
        )
    return root.child_path(path.name)
