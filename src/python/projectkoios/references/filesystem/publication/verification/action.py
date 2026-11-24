from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import final

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.publication.error import (
    FilesystemPublicationError,
)
from projectkoios.references.filesystem.root.descriptor import RootDescriptor

_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_MAX_STREAMED_FILE_BYTES = 4_000_000_000


@final
@dataclass(frozen=True, slots=True, eq=False)
class PublishedFileVerifier:
    """Verify a published pathname still names exact expected bytes."""

    _descriptor: RootDescriptor

    @property
    def label(self) -> str:
        return self._descriptor.label

    def verify(
        self,
        *,
        parent: int,
        leaf: str,
        safe: PurePosixPath,
        expected_sha256: str,
        expected_size: int,
        chunk_bytes: int = 1_048_576,
    ) -> None:
        descriptor = -1
        try:
            descriptor = os.open(leaf, _FILE_FLAGS, dir_fd=parent)
            before = os.fstat(descriptor)
            self._descriptor._require_root_device(before, safe=safe)
            self._descriptor._require_mount_identity(descriptor, safe=safe)
            if not stat.S_ISREG(before.st_mode):
                raise FilesystemPublicationError(
                    f"{self.label} published child is not regular: {safe}"
                )
            digest = hashlib.sha256()
            total = 0
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while True:
                    block = stream.read(chunk_bytes)
                    if not block:
                        break
                    total += len(block)
                    if total > expected_size:
                        break
                    digest.update(block)
            after = os.fstat(descriptor)
            if (
                platform.file_identity(metadata=before)
                != platform.file_identity(metadata=after)
                or total != expected_size
                or after.st_size != expected_size
                or digest.hexdigest() != expected_sha256
            ):
                raise FilesystemPublicationError(
                    f"{self.label} published child identity differs: {safe}"
                )
            self._descriptor._require_open_leaf_identity(
                parent=parent,
                leaf=leaf,
                opened=after,
                safe=safe,
                operation="published",
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
