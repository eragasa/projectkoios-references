"""Descriptor traversal bound to an immutable authorized-root identity."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import final

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.descriptor import error as errors
from projectkoios.references.filesystem.path import validation
from projectkoios.references.filesystem.root.identity import (
    AuthorizedRootIdentity,
)
from projectkoios.references.filesystem.root.preflight.evidence import (
    RootPreflightEvidence,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@final
@dataclass(frozen=True, slots=True, eq=False)
class RootDescriptor:
    """Descriptor-confined access bound to one immutable root identity."""

    _identity: AuthorizedRootIdentity

    @property
    def identity(self) -> AuthorizedRootIdentity:
        return self._identity

    @property
    def path(self) -> Path:
        return self._identity.path

    @property
    def label(self) -> str:
        return self._identity.label

    @property
    def device(self) -> int:
        return self._identity.device

    @property
    def inode(self) -> int:
        return self._identity.inode

    @property
    def mount_id(self) -> int | None:
        return self._identity.mount_id

    @property
    def preflight_evidence(self) -> RootPreflightEvidence:
        return self._identity.preflight_evidence

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
        current = platform.mount_identity(descriptor=descriptor)
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
            raise errors.FilesystemDescriptorError(
                f"{self.label} child changed or was replaced while it was "
                f"{operation}: {safe}"
            ) from error
        self._require_root_device(current, safe=safe)
        if not stat.S_ISREG(current.st_mode) or platform.file_identity(
            metadata=current
        ) != platform.file_identity(metadata=opened):
            raise errors.FilesystemDescriptorError(
                f"{self.label} child changed or was replaced while it was "
                f"{operation}: {safe}"
            )

    def _open_root(self) -> int:
        descriptor = platform.open_directory(path=self.path, label=self.label)
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
                raise errors.FilesystemDescriptorError(
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
                    platform.raise_path_error(
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
