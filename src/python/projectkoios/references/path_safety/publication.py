"""Atomic local publication through authorized-root descriptors."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Self

from projectkoios.references.path_safety import (
    errors,
    platform,
    preflight,
    validation,
)
from projectkoios.references.path_safety.authorization import (
    AuthorizedRootIdentity,
)
from projectkoios.references.path_safety.observation import (
    AuthorizedRootObservation,
)

_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_MAX_STREAMED_FILE_BYTES = 4_000_000_000


class AuthorizedRootPublication(AuthorizedRootIdentity):
    """Own local mutation and publication for an authorized root."""

    __slots__ = ()

    def remove_file_if_exact(
        self,
        relative: str | PurePosixPath,
        *,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
        chunk_bytes: int = 1_048_576,
    ) -> None:
        """Fail closed because portable conditional unlink is unavailable."""
        self._require_local_mutation()
        if (
            not 0 <= expected_size <= max_bytes <= _MAX_STREAMED_FILE_BYTES
            or not 0 < chunk_bytes <= 8_000_000
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise ValueError("exact-removal limits or identity are invalid")
        safe = validation.validate_relative_path(relative)
        raise errors.PathSafetyError(
            "exact rollback is disabled because portable conditional unlink "
            f"cannot bind deletion to the verified inode: {safe}"
        )

    def create_directory(
        self,
        relative: str | PurePosixPath,
    ) -> Self:
        """Create and bind one confined child directory."""
        self._require_local_mutation()
        safe = validation.validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        child = -1
        try:
            child, metadata = (
                platform.DescriptorFilesystem.create_directory_entry(
                    parent=parent,
                    leaf=safe.parts[-1],
                    label=f"{self.label} child {safe}",
                )
            )
            self._require_root_device(metadata, safe=safe)
            self._require_mount_identity(child, safe=safe)
        except FileExistsError:
            raise FileExistsError(self.child_path(safe)) from None
        except OSError as error:
            platform.DescriptorFilesystem.raise_path_error(
                error=error,
                message=(
                    f"cannot safely create {self.label} child directory: {safe}"
                ),
            )
        finally:
            if child >= 0:
                os.close(child)
            os.close(parent)
        return type(self)(
            path=self.child_path(safe),
            label=f"{self.label} child {safe}",
            device=metadata.st_dev,
            inode=metadata.st_ino,
            preflight_evidence=self.preflight_evidence,
            placeholder_probe=self.placeholder_probe,
            mount_id=self.mount_id,
        )

    def rename_child(
        self,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
    ) -> Path:
        """Deprecated: directory no-replace rename is not portable or safe."""
        self._require_local_mutation()
        validation.validate_relative_path(source, field="source")
        validation.validate_relative_path(destination, field="destination")
        raise errors.PathSafetyError(
            "rename_child is disabled because portable atomic no-replace "
            "directory rename is unavailable"
        )

    def write_bytes(
        self,
        relative: str | PurePosixPath,
        content: bytes,
        *,
        replace: bool,
    ) -> Path:
        """Atomically create one confined file from an anonymous descriptor."""
        self._require_local_mutation()
        if type(replace) is not bool:
            raise ValueError("replace must be a bool")
        safe = validation.validate_relative_path(relative)
        if replace:
            raise errors.PathSafetyError(
                "file replacement is disabled because portable publication "
                "cannot bind a replacing rename to the verified inode"
            )
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
                    raise errors.PathSafetyError(
                        f"{self.label} destination must not be a symlink: "
                        f"{safe}"
                    )
                if not stat.S_ISREG(existing.st_mode):
                    raise errors.PathSafetyError(
                        f"{self.label} destination is not a regular file: "
                        f"{safe}"
                    )
                raise FileExistsError(self.child_path(safe))
            descriptor = platform.DescriptorFilesystem.open_anonymous_file(
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
                raise errors.PathSafetyError(
                    f"{self.label} staged bytes are unstable: {safe}"
                )
            digest = hashlib.sha256(content).hexdigest()
            platform.DescriptorFilesystem.publish_open_file_no_replace(
                parent=parent,
                descriptor=descriptor,
                destination=leaf,
            )
            self._require_published_file(
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

    def copy_file_from(
        self,
        source_root: AuthorizedRootObservation,
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
            raise errors.PathLimitError(
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
                    raise errors.PathSafetyError(
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
                platform.DescriptorFilesystem.raise_path_error(
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
                raise errors.PathSafetyError(
                    f"{source_root.label} child is not a regular file: "
                    f"{safe_source}"
                )
            if before.st_size > max_bytes:
                raise errors.PathLimitError(
                    resource=f"{source_root.label} child {safe_source}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            destination_descriptor = (
                platform.DescriptorFilesystem.open_anonymous_file(
                    parent=destination_parent,
                    label=f"{self.label} child {safe_destination}",
                )
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
                        raise errors.PathLimitError(
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
                platform.DescriptorFilesystem.file_identity(metadata=before)
                != platform.DescriptorFilesystem.file_identity(metadata=after)
                or total != after.st_size
            ):
                raise errors.PathSafetyError(
                    f"{source_root.label} child changed while copied: "
                    f"{safe_source}"
                )
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise errors.PathSafetyError(
                    "source identity changed after its recorded observation"
                )
            staged = os.fstat(destination_descriptor)
            if not stat.S_ISREG(staged.st_mode) or staged.st_size != total:
                raise errors.PathSafetyError(
                    f"{self.label} staged bytes are unstable: "
                    f"{safe_destination}"
                )
            platform.DescriptorFilesystem.publish_open_file_no_replace(
                parent=destination_parent,
                descriptor=destination_descriptor,
                destination=safe_destination.parts[-1],
            )
            self._require_published_file(
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

    def _require_published_file(
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
            self._require_root_device(before, safe=safe)
            self._require_mount_identity(descriptor, safe=safe)
            if not stat.S_ISREG(before.st_mode):
                raise errors.PathSafetyError(
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
                platform.DescriptorFilesystem.file_identity(metadata=before)
                != platform.DescriptorFilesystem.file_identity(metadata=after)
                or total != expected_size
                or after.st_size != expected_size
                or digest.hexdigest() != expected_sha256
            ):
                raise errors.PathSafetyError(
                    f"{self.label} published child identity differs: {safe}"
                )
            self._require_open_leaf_identity(
                parent=parent,
                leaf=leaf,
                opened=after,
                safe=safe,
                operation="published",
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _require_local_mutation(self) -> None:
        if (
            self.preflight_evidence.storage_class
            is preflight.RootStorageClass.CLOUD_BACKED
        ):
            raise errors.CloudRootMutationError(
                "cloud-backed root mutation is outside default behavior"
            )
