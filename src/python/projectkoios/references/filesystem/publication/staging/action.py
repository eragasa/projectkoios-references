from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, final

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.limit.error import FilesystemLimitError
from projectkoios.references.filesystem.path import validation
from projectkoios.references.filesystem.publication.error import (
    FilesystemPublicationError,
)
from projectkoios.references.filesystem.publication.result import (
    AddressedFilePublication,
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
class AnonymousFilePublisher:
    """Stage anonymous bytes and publish them without replacement."""

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

    def create_bytes(
        self,
        relative: str | PurePosixPath,
        content: bytes,
    ) -> Path:
        """Atomically create one confined file without replacement."""
        self._require_local_mutation()
        safe = validation.validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        leaf = safe.parts[-1]
        descriptor = -1
        try:
            try:
                existing = os.stat(
                    leaf,
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None
            if existing is not None:
                self._require_root_device(existing, safe=safe)
                if stat.S_ISLNK(existing.st_mode):
                    raise FilesystemPublicationError(
                        f"{self.label} destination must not be a symlink: "
                        f"{safe}"
                    )
                if not stat.S_ISREG(existing.st_mode):
                    raise FilesystemPublicationError(
                        f"{self.label} destination is not a regular file: "
                        f"{safe}"
                    )
                raise FileExistsError(self.child_path(safe))
            descriptor = platform.open_anonymous_file(
                parent=parent,
                label=f"{self.label} child {safe}",
            )
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            staged = os.fstat(descriptor)
            if not stat.S_ISREG(staged.st_mode) or staged.st_size != len(
                content
            ):
                raise FilesystemPublicationError(
                    f"{self.label} staged bytes are unstable: {safe}"
                )
            digest = hashlib.sha256(content).hexdigest()
            platform.publish_open_file_no_replace(
                parent=parent,
                descriptor=descriptor,
                destination=leaf,
            )
            self._verifier.verify(
                parent=parent,
                leaf=leaf,
                safe=safe,
                expected_sha256=digest,
                expected_size=len(content),
            )
        except FileExistsError:
            raise FileExistsError(self.child_path(safe)) from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)
        return self.child_path(safe)

    def publish_addressed_stream(
        self,
        stream: BinaryIO,
        *,
        suffix: str,
        max_bytes: int,
        required_prefix: bytes = b"",
        expected_size: int | None = None,
        chunk_bytes: int = 1_048_576,
    ) -> AddressedFilePublication:
        """Publish a bounded stream under its SHA-256 digest without replace."""
        self._require_local_mutation()
        if (
            type(suffix) is not str
            or re.fullmatch(r"\.[a-z0-9]{1,15}", suffix) is None
            or type(required_prefix) is not bytes
            or len(required_prefix) > 64
            or not 1 <= max_bytes <= _MAX_STREAMED_FILE_BYTES
            or not 0 < chunk_bytes <= 8_000_000
            or (
                expected_size is not None
                and (
                    type(expected_size) is not int
                    or not 1 <= expected_size <= max_bytes
                )
            )
        ):
            raise ValueError("stream-publication limits are invalid")
        parent = self._open_root()
        descriptor = -1
        digest = hashlib.sha256()
        total = 0
        prefix = bytearray()
        try:
            descriptor = platform.open_anonymous_file(
                parent=parent,
                label=f"{self.label} content-addressed stream",
            )
            with os.fdopen(descriptor, "wb", closefd=False) as writer:
                while True:
                    block = stream.read(min(chunk_bytes, max_bytes - total + 1))
                    if not block:
                        break
                    if type(block) is not bytes:
                        raise ValueError("stream must return bytes")
                    total += len(block)
                    if total > max_bytes:
                        raise FilesystemLimitError(
                            resource=f"{self.label} input stream",
                            limit_name="max_file_bytes",
                            limit=max_bytes,
                            observed=total,
                        )
                    if len(prefix) < len(required_prefix):
                        prefix.extend(
                            block[: len(required_prefix) - len(prefix)]
                        )
                    digest.update(block)
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            if total == 0:
                raise ValueError("stream must not be empty")
            if bytes(prefix) != required_prefix:
                raise ValueError("stream does not have the required prefix")
            if expected_size is not None and total != expected_size:
                raise ValueError("stream size differs from expected_size")
            staged = os.fstat(descriptor)
            if not stat.S_ISREG(staged.st_mode) or staged.st_size != total:
                raise FilesystemPublicationError(
                    f"{self.label} staged bytes are unstable"
                )
            sha256 = digest.hexdigest()
            leaf = f"{sha256}{suffix}"
            safe = validation.validate_relative_path(leaf)
            try:
                platform.publish_open_file_no_replace(
                    parent=parent,
                    descriptor=descriptor,
                    destination=leaf,
                )
                created = True
            except FileExistsError:
                created = False
            self._verifier.verify(
                parent=parent,
                leaf=leaf,
                safe=safe,
                expected_sha256=sha256,
                expected_size=total,
                chunk_bytes=chunk_bytes,
            )
            return AddressedFilePublication(
                path=self.child_path(safe),
                sha256=sha256,
                byte_size=total,
                created=created,
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)
