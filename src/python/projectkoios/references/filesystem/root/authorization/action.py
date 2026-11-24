"""Authorize immutable root identity before runtime capability creation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.descriptor import error as errors
from projectkoios.references.filesystem.root.error import CloudRootMutationError
from projectkoios.references.filesystem.root.identity import (
    AuthorizedRootIdentity,
)
from projectkoios.references.filesystem.root.preflight.action import (
    authorize_root_preflight,
)
from projectkoios.references.filesystem.root.preflight.probe import (
    CloudPlaceholderProbe,
    RootBoundPlaceholderProbeFactory,
    RootPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def authorize_existing_root(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: RootPlaceholderProbe | None = None,
) -> tuple[AuthorizedRootIdentity, CloudPlaceholderProbe | None]:
    """Bind an existing directory without following any path symlink."""
    root_preflight = authorize_root_preflight(
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    supplied = Path(os.path.abspath(os.fspath(path.expanduser())))
    concrete_probe = (
        placeholder_probe
        if isinstance(placeholder_probe, RootBoundPlaceholderProbeFactory)
        else None
    )
    if concrete_probe is not None and (
        not concrete_probe.matches_root_path(supplied)
    ):
        raise errors.FilesystemDescriptorError(
            "root-bound placeholder probe names a different root"
        )
    anchor = Path(supplied.anchor)
    descriptor = platform.open_directory(path=anchor, label=f"{label} anchor")
    try:
        for part in supplied.parts[1:]:
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError as error:
                raise errors.FilesystemDescriptorError(
                    f"{label} does not exist"
                ) from error
            except OSError as error:
                platform.raise_path_error(
                    error=error,
                    message=f"cannot safely traverse {label}: {part}",
                )
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        mount_id = platform.mount_identity(descriptor=descriptor)
        if sys.platform.startswith("linux") and mount_id is None:
            raise errors.FilesystemBoundaryError(
                f"cannot establish the mount boundary for {label}"
            )
        bound_probe = cast(CloudPlaceholderProbe | None, placeholder_probe)
        if concrete_probe is not None:
            bound_probe = concrete_probe.bind_authorized_root(
                supplied, device=metadata.st_dev, inode=metadata.st_ino
            )
            if bound_probe is None:
                raise errors.FilesystemDescriptorError(
                    "root-bound placeholder probe identity is ambiguous"
                )
        identity = AuthorizedRootIdentity(
            path=supplied,
            label=label,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            preflight_evidence=root_preflight,
            mount_id=mount_id,
        )
        return (identity, bound_probe)
    finally:
        os.close(descriptor)


def create_root_identity(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: RootPlaceholderProbe | None = None,
) -> AuthorizedRootIdentity:
    """Create, then bind, a real authorized directory."""
    if storage_class is RootStorageClass.CLOUD_BACKED:
        raise CloudRootMutationError(
            "cloud-backed root creation requires external authorization"
        )
    root_preflight = authorize_root_preflight(
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    supplied = Path(os.path.abspath(os.fspath(path.expanduser())))
    anchor = Path(supplied.anchor)
    descriptor = platform.open_directory(path=anchor, label=f"{label} anchor")
    try:
        for part in supplied.parts[1:]:
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    child, _ = platform.create_directory_entry(
                        parent=descriptor, leaf=part, label=label
                    )
                except FileExistsError:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except OSError as error:
                platform.raise_path_error(
                    error=error,
                    message=f"cannot safely create or traverse {label}: {part}",
                )
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        mount_id = platform.mount_identity(descriptor=descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    os.close(descriptor)
    if sys.platform.startswith("linux") and mount_id is None:
        raise errors.FilesystemBoundaryError(
            f"cannot establish the mount boundary for {label}"
        )
    return AuthorizedRootIdentity(
        path=supplied,
        label=label,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        preflight_evidence=root_preflight,
        mount_id=mount_id,
    )
