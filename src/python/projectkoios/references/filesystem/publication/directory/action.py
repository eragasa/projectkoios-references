from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import final

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.path import validation
from projectkoios.references.filesystem.root.descriptor import RootDescriptor
from projectkoios.references.filesystem.root.error import CloudRootMutationError
from projectkoios.references.filesystem.root.identity import (
    AuthorizedRootIdentity,
)
from projectkoios.references.filesystem.root.preflight.evidence import (
    RootPreflightEvidence,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)

_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_MAX_STREAMED_FILE_BYTES = 4_000_000_000


@final
@dataclass(frozen=True, slots=True, eq=False)
class DirectoryPublisher:
    """Create and bind a confined directory without replacement."""

    _descriptor: RootDescriptor

    @property
    def label(self) -> str:
        return self._descriptor.label

    @property
    def preflight_evidence(self) -> RootPreflightEvidence:
        return self._descriptor.preflight_evidence

    @property
    def mount_id(self) -> int | None:
        return self._descriptor.mount_id

    def child_path(self, relative: str | PurePosixPath) -> Path:
        return self._descriptor.child_path(relative)

    def _open_root(self) -> int:
        return self._descriptor._open_root()

    def _open_parent(self, parts: tuple[str, ...]) -> int:
        return self._descriptor._open_parent(parts)

    def _require_root_device(
        self, metadata: os.stat_result, *, safe: PurePosixPath
    ) -> None:
        self._descriptor._require_root_device(metadata, safe=safe)

    def _require_mount_identity(
        self, descriptor: int, *, safe: PurePosixPath
    ) -> None:
        self._descriptor._require_mount_identity(descriptor, safe=safe)

    def _require_local_mutation(self) -> None:
        if (
            self.preflight_evidence.storage_class
            is RootStorageClass.CLOUD_BACKED
        ):
            raise CloudRootMutationError(
                "cloud-backed root mutation is outside default behavior"
            )

    def create_directory(
        self,
        relative: str | PurePosixPath,
    ) -> AuthorizedRootIdentity:
        """Create and bind one confined child directory."""
        self._require_local_mutation()
        safe = validation.validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        child = -1
        try:
            child, metadata = platform.create_directory_entry(
                parent=parent,
                leaf=safe.parts[-1],
                label=f"{self.label} child {safe}",
            )
            self._require_root_device(metadata, safe=safe)
            self._require_mount_identity(child, safe=safe)
        except FileExistsError:
            raise FileExistsError(self.child_path(safe)) from None
        except OSError as error:
            platform.raise_path_error(
                error=error,
                message=(
                    f"cannot safely create {self.label} child directory: {safe}"
                ),
            )
        finally:
            if child >= 0:
                os.close(child)
            os.close(parent)
        return AuthorizedRootIdentity(
            path=self.child_path(safe),
            label=f"{self.label} child {safe}",
            device=metadata.st_dev,
            inode=metadata.st_ino,
            preflight_evidence=self.preflight_evidence,
            mount_id=self.mount_id,
        )
