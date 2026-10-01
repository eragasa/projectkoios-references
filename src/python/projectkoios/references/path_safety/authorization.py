"""Authorized-root identity and descriptor traversal."""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Self

from projectkoios.references.path_safety import (
    errors,
    platform,
    preflight,
    probes,
    validation,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@dataclass(frozen=True, slots=True)
class AuthorizedRootIdentity:
    """Bind one stable directory identity and its declared storage policy."""

    path: Path
    label: str
    device: int
    inode: int
    preflight_evidence: preflight.RootPreflightEvidence
    placeholder_probe: preflight.CloudPlaceholderProbe | None
    mount_id: int | None = None

    @classmethod
    def existing(
        cls,
        path: Path,
        *,
        label: str,
        root_alias: str,
        storage_class: preflight.RootStorageClass,
        placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
    ) -> Self:
        """Bind an existing directory without following any path symlink."""
        root_preflight = probes.authorize_root_preflight(
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        supplied = Path(os.path.abspath(os.fspath(path.expanduser())))
        concrete_probe = (
            placeholder_probe
            if isinstance(
                placeholder_probe,
                probes.MacOSFileProviderPlaceholderProbe,
            )
            else None
        )
        if concrete_probe is not None and not concrete_probe.matches_root_path(
            supplied
        ):
            raise errors.PathSafetyError(
                "macOS File Provider probe is bound to a different root"
            )
        anchor = Path(supplied.anchor)
        descriptor = platform.DescriptorFilesystem.open_directory(
            path=anchor,
            label=f"{label} anchor",
        )
        try:
            for part in supplied.parts[1:]:
                try:
                    child = os.open(
                        part,
                        _DIRECTORY_FLAGS,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError as error:
                    raise errors.PathSafetyError(
                        f"{label} does not exist"
                    ) from error
                except OSError as error:
                    platform.DescriptorFilesystem.raise_path_error(
                        error=error,
                        message=(f"cannot safely traverse {label}: {part}"),
                    )
                os.close(descriptor)
                descriptor = child
            metadata = os.fstat(descriptor)
            mount_id = platform.DescriptorFilesystem.mount_identity(
                descriptor=descriptor
            )
            if sys.platform.startswith("linux") and mount_id is None:
                raise errors.FilesystemBoundaryError(
                    f"cannot establish the mount boundary for {label}"
                )
            if concrete_probe is not None and not (
                concrete_probe.bind_authorized_root(
                    supplied,
                    device=metadata.st_dev,
                    inode=metadata.st_ino,
                )
            ):
                raise errors.PathSafetyError(
                    "macOS File Provider probe root identity is ambiguous"
                )
            return cls(
                path=supplied,
                label=label,
                device=metadata.st_dev,
                inode=metadata.st_ino,
                preflight_evidence=root_preflight,
                placeholder_probe=(
                    placeholder_probe
                    if storage_class is preflight.RootStorageClass.CLOUD_BACKED
                    else None
                ),
                mount_id=mount_id,
            )
        finally:
            os.close(descriptor)

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        label: str,
        root_alias: str,
        storage_class: preflight.RootStorageClass,
        placeholder_probe: preflight.CloudPlaceholderProbe | None = None,
    ) -> Self:
        """Create, then bind, a real authorized directory."""
        if storage_class is preflight.RootStorageClass.CLOUD_BACKED:
            raise errors.CloudRootMutationError(
                "cloud-backed root creation requires external authorization"
            )
        root_preflight = probes.authorize_root_preflight(
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        supplied = Path(os.path.abspath(os.fspath(path.expanduser())))
        anchor = Path(supplied.anchor)
        descriptor = platform.DescriptorFilesystem.open_directory(
            path=anchor, label=f"{label} anchor"
        )
        try:
            for part in supplied.parts[1:]:
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except FileNotFoundError:
                    try:
                        child, _ = (
                            platform.DescriptorFilesystem.create_directory_entry(
                                parent=descriptor,
                                leaf=part,
                                label=label,
                            )
                        )
                    except FileExistsError:
                        child = os.open(
                            part, _DIRECTORY_FLAGS, dir_fd=descriptor
                        )
                except OSError as error:
                    platform.DescriptorFilesystem.raise_path_error(
                        error=error,
                        message=(
                            f"cannot safely create or traverse {label}: {part}"
                        ),
                    )
                os.close(descriptor)
                descriptor = child
            metadata = os.fstat(descriptor)
            mount_id = platform.DescriptorFilesystem.mount_identity(
                descriptor=descriptor
            )
        except BaseException:
            os.close(descriptor)
            raise
        os.close(descriptor)
        if sys.platform.startswith("linux") and mount_id is None:
            raise errors.FilesystemBoundaryError(
                f"cannot establish the mount boundary for {label}"
            )
        return cls(
            path=supplied,
            label=label,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            preflight_evidence=root_preflight,
            placeholder_probe=None,
            mount_id=mount_id,
        )

    def child_path(self, relative: str | PurePosixPath) -> Path:
        """Render a validated child path for reporting only."""
        safe = validation.validate_relative_path(relative)
        return self.path.joinpath(*safe.parts)

    def _require_root_device(
        self,
        metadata: os.stat_result,
        *,
        safe: PurePosixPath,
    ) -> None:
        if metadata.st_dev != self.device:
            raise errors.FilesystemBoundaryError(
                f"{self.label} crosses a filesystem boundary: {safe}"
            )

    def _require_mount_identity(
        self,
        descriptor: int,
        *,
        safe: PurePosixPath,
    ) -> None:
        if self.mount_id is None:
            return
        current = platform.DescriptorFilesystem.mount_identity(
            descriptor=descriptor
        )
        if current is None or current != self.mount_id:
            raise errors.FilesystemBoundaryError(
                f"{self.label} crosses a mount boundary: {safe}"
            )

    def _require_open_leaf_identity(
        self,
        *,
        parent: int,
        leaf: str,
        opened: os.stat_result,
        safe: PurePosixPath,
        operation: str,
    ) -> None:
        """Require the pathname to still name the opened stable inode."""
        self._require_root_device(opened, safe=safe)
        try:
            current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            raise errors.PathSafetyError(
                f"{self.label} child changed or was replaced while it was "
                f"{operation}: {safe}"
            ) from error
        self._require_root_device(current, safe=safe)
        if not stat.S_ISREG(
            current.st_mode
        ) or platform.DescriptorFilesystem.file_identity(
            metadata=current
        ) != platform.DescriptorFilesystem.file_identity(metadata=opened):
            raise errors.PathSafetyError(
                f"{self.label} child changed or was replaced while it was "
                f"{operation}: {safe}"
            )

    def _open_root(self) -> int:
        descriptor = platform.DescriptorFilesystem.open_directory(
            path=self.path, label=self.label
        )
        try:
            metadata = os.fstat(descriptor)
            self._require_mount_identity(
                descriptor,
                safe=PurePosixPath("."),
            )
            if (metadata.st_dev, metadata.st_ino) != (
                self.device,
                self.inode,
            ):
                raise errors.PathSafetyError(
                    f"{self.label} changed after it was authorized"
                )
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _open_parent(self, parts: tuple[str, ...]) -> int:
        descriptor = self._open_root()
        try:
            for index, part in enumerate(parts):
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except OSError as error:
                    platform.DescriptorFilesystem.raise_path_error(
                        error=error,
                        message=(
                            f"{self.label} path contains a symlink or "
                            f"non-directory component: {part}"
                        ),
                    )
                try:
                    child_metadata = os.fstat(child)
                except OSError:
                    os.close(child)
                    raise
                relative = PurePosixPath(*parts[: index + 1])
                if child_metadata.st_dev != self.device:
                    os.close(child)
                    raise errors.FilesystemBoundaryError(
                        f"{self.label} crosses a filesystem boundary: "
                        f"{relative}"
                    )
                try:
                    self._require_mount_identity(child, safe=relative)
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise
