"""Bounded byte observations through authorized-root descriptors."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import PurePosixPath
from typing import Literal

from projectkoios.references.path_safety import (
    errors,
    inventory,
    platform,
    preflight,
    validation,
)
from projectkoios.references.path_safety.authorization import (
    AuthorizedRootIdentity,
)

_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_MAX_STREAMED_FILE_BYTES = 4_000_000_000
_DEFAULT_READ_MAX_BYTES = 50_000_000


class AuthorizedRootObservation(AuthorizedRootIdentity):
    """Own bounded observations for an authorized root."""

    __slots__ = ()

    def state(
        self,
        relative: str | PurePosixPath,
    ) -> Literal["missing", "regular", "directory"]:
        """Classify a confined child without following symlinks."""
        safe = validation.validate_relative_path(relative)
        try:
            parent = self._open_parent(safe.parts[:-1])
        except FileNotFoundError:
            return "missing"
        try:
            try:
                metadata = os.stat(
                    safe.parts[-1], dir_fd=parent, follow_symlinks=False
                )
            except FileNotFoundError:
                return "missing"
            self._require_root_device(metadata, safe=safe)
            if stat.S_ISLNK(metadata.st_mode):
                raise errors.PathSafetyError(
                    f"{self.label} child must not be a symlink: {safe}"
                )
            if stat.S_ISREG(metadata.st_mode):
                return "regular"
            if stat.S_ISDIR(metadata.st_mode):
                return "directory"
            raise errors.PathSafetyError(
                f"{self.label} child is not a regular file or directory: {safe}"
            )
        finally:
            os.close(parent)

    def preflight_file(
        self,
        relative: str | PurePosixPath,
    ) -> preflight.PlaceholderObservation:
        """Classify a candidate using metadata only before opening its bytes."""
        safe = validation.validate_relative_path(relative)
        evidence = self.preflight_evidence
        if evidence.storage_class is preflight.RootStorageClass.CLOUD_BACKED:
            probe = self.placeholder_probe
            if probe is None:
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.UNSUPPORTED_PLATFORM
                )
            try:
                status = probe.observe(
                    root_alias=evidence.root_alias,
                    relative_path=safe,
                )
            except Exception:
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.AMBIGUOUS
                )
            if not isinstance(status, preflight.PlaceholderStatus):
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.AMBIGUOUS
                )
            if status is not preflight.PlaceholderStatus.ORDINARY_FILE:
                return self._preflight_observation(safe, status)
        try:
            parent = self._open_parent(safe.parts[:-1])
        except FileNotFoundError:
            return self._preflight_observation(
                safe, preflight.PlaceholderStatus.MISSING
            )
        except errors.FilesystemBoundaryError:
            return self._preflight_observation(
                safe, preflight.PlaceholderStatus.FILESYSTEM_BOUNDARY
            )
        except PermissionError:
            return self._preflight_observation(
                safe, preflight.PlaceholderStatus.ACCESS_CONTROLLED
            )
        try:
            try:
                metadata = os.stat(
                    safe.parts[-1],
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.MISSING
                )
            except PermissionError:
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.ACCESS_CONTROLLED
                )
            if metadata.st_dev != self.device:
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.FILESYSTEM_BOUNDARY
                )
            if stat.S_ISLNK(metadata.st_mode):
                raise errors.PathSafetyError(
                    f"{self.label} child must not be a symlink: {safe}"
                )
            if not stat.S_ISREG(metadata.st_mode):
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.AMBIGUOUS
                )
            read_bits = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            if metadata.st_mode & read_bits == 0:
                return self._preflight_observation(
                    safe, preflight.PlaceholderStatus.UNREADABLE
                )
            return self._preflight_observation(
                safe, preflight.PlaceholderStatus.ORDINARY_FILE
            )
        finally:
            os.close(parent)

    def require_readable_file(
        self,
        relative: str | PurePosixPath,
    ) -> preflight.PlaceholderObservation:
        """Fail closed unless metadata preflight permits byte access."""
        observation = self.preflight_file(relative)
        if observation.status is preflight.PlaceholderStatus.ORDINARY_FILE:
            if observation.storage_class is preflight.RootStorageClass.LOCAL:
                return observation
            raise preflight.PlaceholderPreflightError(
                self._preflight_observation(
                    validation.validate_relative_path(relative),
                    preflight.PlaceholderStatus.ACCESS_CONTROLLED,
                )
            )
        if observation.storage_class is preflight.RootStorageClass.CLOUD_BACKED:
            raise preflight.PlaceholderPreflightError(observation)
        if observation.status is preflight.PlaceholderStatus.MISSING:
            raise FileNotFoundError(observation.relative_path)
        if observation.status in {
            preflight.PlaceholderStatus.ACCESS_CONTROLLED,
            preflight.PlaceholderStatus.UNREADABLE,
        }:
            raise PermissionError(
                "candidate byte access denied by metadata preflight"
            )
        raise preflight.PlaceholderPreflightError(observation)

    def _preflight_observation(
        self,
        relative: PurePosixPath,
        status: preflight.PlaceholderStatus,
    ) -> preflight.PlaceholderObservation:
        evidence = self.preflight_evidence
        return preflight.PlaceholderObservation(
            root_alias=evidence.root_alias,
            relative_path=relative.as_posix(),
            storage_class=evidence.storage_class,
            probe_id=evidence.probe_id,
            status=status,
        )

    def read_bytes(
        self,
        relative: str | PurePosixPath,
        *,
        max_bytes: int = _DEFAULT_READ_MAX_BYTES,
    ) -> bytes:
        """Read one regular file through no-follow directory descriptors."""
        safe = validation.validate_relative_path(relative)
        self.require_readable_file(safe)
        parent = self._open_parent(safe.parts[:-1])
        descriptor = -1
        try:
            try:
                descriptor = os.open(safe.parts[-1], _FILE_FLAGS, dir_fd=parent)
            except OSError as error:
                platform.DescriptorFilesystem.raise_path_error(
                    error=error,
                    message=f"cannot safely open {self.label} child: {safe}",
                )
            before = os.fstat(descriptor)
            self._require_root_device(before, safe=safe)
            self._require_mount_identity(descriptor, safe=safe)
            if not stat.S_ISREG(before.st_mode):
                raise errors.PathSafetyError(
                    f"{self.label} child is not a regular file: {safe}"
                )
            if (
                type(max_bytes) is not int
                or not 0 <= max_bytes <= _DEFAULT_READ_MAX_BYTES
            ):
                raise ValueError(
                    "max_bytes must be a nonnegative integer within the "
                    "bounded-read ceiling"
                )
            if before.st_size > max_bytes:
                raise errors.PathLimitError(
                    resource=f"{self.label} child {safe}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise errors.PathLimitError(
                    resource=f"{self.label} child {safe}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=len(data),
                )
            after = os.fstat(descriptor)
            if (
                platform.DescriptorFilesystem.file_identity(metadata=before)
                != platform.DescriptorFilesystem.file_identity(metadata=after)
                or len(data) != after.st_size
            ):
                raise errors.PathSafetyError(
                    f"{self.label} child changed while it was read: {safe}"
                )
            self._require_open_leaf_identity(
                parent=parent,
                leaf=safe.parts[-1],
                opened=after,
                safe=safe,
                operation="read",
            )
            return data
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)

    def read_text(
        self,
        relative: str | PurePosixPath,
        *,
        encoding: str = "utf-8",
        max_bytes: int = _DEFAULT_READ_MAX_BYTES,
    ) -> str:
        """Read and decode one confined regular file."""
        return self.read_bytes(relative, max_bytes=max_bytes).decode(encoding)

    def observe_file(
        self,
        relative: str | PurePosixPath,
        *,
        max_bytes: int,
        prefix_bytes: int = 0,
        chunk_bytes: int = 1_048_576,
    ) -> inventory.FileObservation:
        """Hash and size one file in bounded memory through one descriptor."""
        if (
            not 0 <= max_bytes <= _MAX_STREAMED_FILE_BYTES
            or not 0 <= prefix_bytes <= 1_000_000
            or not 0 < chunk_bytes <= 8_000_000
        ):
            raise ValueError("file observation limits are invalid")
        safe = validation.validate_relative_path(relative)
        self.require_readable_file(safe)
        parent = self._open_parent(safe.parts[:-1])
        descriptor = -1
        try:
            try:
                descriptor = os.open(safe.parts[-1], _FILE_FLAGS, dir_fd=parent)
            except OSError as error:
                platform.DescriptorFilesystem.raise_path_error(
                    error=error,
                    message=f"cannot safely open {self.label} child: {safe}",
                )
            before = os.fstat(descriptor)
            self._require_root_device(before, safe=safe)
            if not stat.S_ISREG(before.st_mode):
                raise errors.PathSafetyError(
                    f"{self.label} child is not a regular file: {safe}"
                )
            self._require_mount_identity(descriptor, safe=safe)
            if before.st_size > max_bytes:
                raise errors.PathLimitError(
                    resource=f"{self.label} child {safe}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            digest = hashlib.sha256()
            prefix = bytearray()
            total = 0
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while True:
                    remaining = max_bytes - total
                    block = stream.read(min(chunk_bytes, remaining + 1))
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise errors.PathLimitError(
                            resource=f"{self.label} child {safe}",
                            limit_name="max_file_bytes",
                            limit=max_bytes,
                            observed=total,
                        )
                    digest.update(block)
                    if len(prefix) < prefix_bytes:
                        prefix.extend(block[: prefix_bytes - len(prefix)])
            after = os.fstat(descriptor)
            if platform.DescriptorFilesystem.file_identity(
                metadata=before
            ) != platform.DescriptorFilesystem.file_identity(
                metadata=after
            ) or total != (after.st_size):
                raise errors.PathSafetyError(
                    f"{self.label} child changed while it was observed: {safe}"
                )
            self._require_open_leaf_identity(
                parent=parent,
                leaf=safe.parts[-1],
                opened=after,
                safe=safe,
                operation="observed",
            )
            return inventory.FileObservation(
                byte_size=total,
                sha256=digest.hexdigest(),
                prefix=bytes(prefix),
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)
