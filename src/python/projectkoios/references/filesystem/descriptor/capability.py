"""Cross-platform descriptor confinement over explicit OS adapters."""

from __future__ import annotations

import errno
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Never

from projectkoios.references.adapters.filesystem.linux import (
    descriptor as linux_descriptor,
)
from projectkoios.references.adapters.filesystem.macos import (
    descriptor as macos_descriptor,
)

from .error import FilesystemDescriptorError

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def mount_identity(*, descriptor: int) -> int | None:
    if sys.platform.startswith("linux"):
        return linux_descriptor.mount_identity(descriptor=descriptor)
    return None


def _rename_directory_no_replace(
    *, parent: int, source: str, destination: str
) -> None:
    if sys.platform.startswith("linux"):
        linux_descriptor.rename_directory_no_replace(
            parent=parent, source=source, destination=destination
        )
        return
    if sys.platform == "darwin":
        macos_descriptor.rename_directory_no_replace(
            parent=parent, source=source, destination=destination
        )
        return
    raise FilesystemDescriptorError(
        "atomic no-replace directory creation is unavailable"
    )


def create_directory_entry(
    *, parent: int, leaf: str, label: str
) -> tuple[int, os.stat_result]:
    temporary = f".koios-dir-{secrets.token_hex(16)}.tmp"
    descriptor = -1
    renamed = False
    try:
        os.mkdir(temporary, mode=448, dir_fd=parent)
        descriptor = os.open(temporary, _DIRECTORY_FLAGS, dir_fd=parent)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise FilesystemDescriptorError(
                f"cannot create directory for {label}"
            )
        _rename_directory_no_replace(
            parent=parent, source=temporary, destination=leaf
        )
        renamed = True
        os.fsync(parent)
        return (descriptor, metadata)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        if not renamed:
            try:
                os.rmdir(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        raise


def open_anonymous_file(*, parent: int, label: str) -> int:
    if sys.platform.startswith("linux"):
        return linux_descriptor.open_anonymous_file(parent=parent, label=label)
    if sys.platform == "darwin":
        return macos_descriptor.open_anonymous_file(parent=parent, label=label)
    raise FilesystemDescriptorError(
        f"descriptor-bound publication is unavailable for {label}"
    )


def publish_open_file_no_replace(
    *, parent: int, descriptor: int, destination: str
) -> None:
    if os.fstat(descriptor).st_nlink != 0:
        raise FilesystemDescriptorError(
            "publication source descriptor is not anonymous"
        )
    if sys.platform.startswith("linux"):
        linux_descriptor.publish_open_file_no_replace(
            parent=parent, descriptor=descriptor, destination=destination
        )
        return
    if sys.platform == "darwin":
        macos_descriptor.publish_open_file_no_replace(
            parent=parent, descriptor=descriptor, destination=destination
        )
        return
    raise FilesystemDescriptorError(
        "descriptor-bound no-replace file publication is unavailable"
    )


def file_identity(
    *, metadata: os.stat_result
) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def open_directory(*, path: Path, label: str) -> int:
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
    except OSError as error:
        raise_path_error(error=error, message=f"cannot safely open {label}")
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise FilesystemDescriptorError(f"{label} must be a directory")
    return descriptor


def raise_path_error(*, error: OSError, message: str) -> Never:
    if error.errno in {errno.ELOOP, errno.ENOTDIR, errno.EPERM, errno.EINVAL}:
        raise FilesystemDescriptorError(message) from error
    raise error
