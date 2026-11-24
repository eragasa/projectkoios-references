from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import final

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.limit.error import FilesystemLimitError
from projectkoios.references.filesystem.observation.capability import (
    RootObservation,
)
from projectkoios.references.filesystem.path import validation
from projectkoios.references.filesystem.publication.error import (
    FilesystemPublicationError,
)
from projectkoios.references.filesystem.publication.verification.action import (
    PublishedFileVerifier,
)
from projectkoios.references.filesystem.root.descriptor import RootDescriptor
from projectkoios.references.filesystem.root.error import CloudRootMutationError
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
class VerifiedFileCopier:
    """Copy an exact observed source into no-replace anonymous staging."""

    _descriptor: RootDescriptor
    _verifier: PublishedFileVerifier

    @property
    def label(self) -> str:
        return self._descriptor.label

    @property
    def preflight_evidence(self) -> RootPreflightEvidence:
        return self._descriptor.preflight_evidence

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

    def copy_file_from(
        self,
        source_root: RootObservation,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
        *,
        max_bytes: int,
        expected_sha256: str,
        expected_size: int,
        chunk_bytes: int = 1_048_576,
    ) -> Path:
        """Stream verified source bytes into an anonymous destination inode."""
        self._require_local_mutation()
        if (
            not 0 <= max_bytes <= _MAX_STREAMED_FILE_BYTES
            or expected_size < 0
            or not 0 < chunk_bytes <= 8_000_000
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise ValueError(
                "file-copy limits or expected identity are invalid"
            )
        if expected_size > max_bytes:
            raise FilesystemLimitError(
                resource=f"{source_root.label} expected source",
                limit_name="max_file_bytes",
                limit=max_bytes,
                observed=expected_size,
            )
        safe_source = validation.validate_relative_path(source, field="source")
        source_root.require_readable_file(safe_source)
        safe_destination = validation.validate_relative_path(
            destination,
            field="destination",
        )
        source_parent = -1
        destination_parent = -1
        source_descriptor = -1
        destination_descriptor = -1
        try:
            source_parent = source_root._open_parent(safe_source.parts[:-1])
            destination_parent = self._open_parent(safe_destination.parts[:-1])
            try:
                existing = os.stat(
                    safe_destination.parts[-1],
                    dir_fd=destination_parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None
            if existing is not None:
                self._require_root_device(existing, safe=safe_destination)
                if stat.S_ISLNK(existing.st_mode):
                    raise FilesystemPublicationError(
                        f"{self.label} destination must not be a symlink: "
                        f"{safe_destination}"
                    )
                raise FileExistsError(self.child_path(safe_destination))
            try:
                source_descriptor = os.open(
                    safe_source.parts[-1],
                    _FILE_FLAGS,
                    dir_fd=source_parent,
                )
            except OSError as error:
                platform.raise_path_error(
                    error=error,
                    message=(
                        f"cannot safely open {source_root.label} child: "
                        f"{safe_source}"
                    ),
                )
            before = os.fstat(source_descriptor)
            source_root._require_root_device(before, safe=safe_source)
            source_root._require_mount_identity(
                source_descriptor,
                safe=safe_source,
            )
            if not stat.S_ISREG(before.st_mode):
                raise FilesystemPublicationError(
                    f"{source_root.label} child is not a regular file: "
                    f"{safe_source}"
                )
            if before.st_size > max_bytes:
                raise FilesystemLimitError(
                    resource=f"{source_root.label} child {safe_source}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            destination_descriptor = platform.open_anonymous_file(
                parent=destination_parent,
                label=f"{self.label} child {safe_destination}",
            )
            digest = hashlib.sha256()
            total = 0
            with (
                os.fdopen(source_descriptor, "rb", closefd=False) as reader,
                os.fdopen(
                    destination_descriptor,
                    "wb",
                    closefd=False,
                ) as writer,
            ):
                while True:
                    block = reader.read(chunk_bytes)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise FilesystemLimitError(
                            resource=(
                                f"{source_root.label} child {safe_source}"
                            ),
                            limit_name="max_file_bytes",
                            limit=max_bytes,
                            observed=total,
                        )
                    digest.update(block)
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            after = os.fstat(source_descriptor)
            if (
                platform.file_identity(metadata=before)
                != platform.file_identity(metadata=after)
                or total != after.st_size
            ):
                raise FilesystemPublicationError(
                    f"{source_root.label} child changed while copied: "
                    f"{safe_source}"
                )
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise FilesystemPublicationError(
                    "source identity changed after its recorded observation"
                )
            staged = os.fstat(destination_descriptor)
            if not stat.S_ISREG(staged.st_mode) or staged.st_size != total:
                raise FilesystemPublicationError(
                    f"{self.label} staged bytes are unstable: "
                    f"{safe_destination}"
                )
            platform.publish_open_file_no_replace(
                parent=destination_parent,
                descriptor=destination_descriptor,
                destination=safe_destination.parts[-1],
            )
            self._verifier.verify(
                parent=destination_parent,
                leaf=safe_destination.parts[-1],
                safe=safe_destination,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                chunk_bytes=chunk_bytes,
            )
        except FileExistsError:
            raise FileExistsError(self.child_path(safe_destination)) from None
        finally:
            if destination_descriptor >= 0:
                os.close(destination_descriptor)
            if source_descriptor >= 0:
                os.close(source_descriptor)
            if source_parent >= 0:
                os.close(source_parent)
            if destination_parent >= 0:
                os.close(destination_parent)
        return self.child_path(safe_destination)
