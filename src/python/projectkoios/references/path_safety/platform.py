"""Low-level descriptor operations shared by authorized roots."""

from __future__ import annotations

import ctypes
import errno
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Never

from projectkoios.references.path_safety import errors

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004


class DescriptorFilesystem:
    """Own platform-specific descriptor identity and atomic creation."""

    __slots__ = ()

    @staticmethod
    def mount_identity(*, descriptor: int) -> int | None:
        """Return the Linux mount identity for an open descriptor."""
        if not sys.platform.startswith("linux"):
            return None
        try:
            with open(
                f"/proc/self/fdinfo/{descriptor}",
                encoding="utf-8",
            ) as stream:
                for line in stream:
                    name, separator, value = line.partition(":")
                    if separator and name == "mnt_id":
                        rendered = value.strip()
                        return int(rendered) if rendered.isascii() else None
        except OSError, ValueError:
            return None
        return None

    @staticmethod
    def _rename_directory_no_replace(
        *,
        parent: int,
        source: str,
        destination: str,
    ) -> None:
        library = ctypes.CDLL(None, use_errno=True)
        source_bytes = os.fsencode(source)
        destination_bytes = os.fsencode(destination)
        if sys.platform == "darwin":
            rename = library.renameatx_np
            rename.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            rename.restype = ctypes.c_int
            result = rename(
                parent,
                source_bytes,
                parent,
                destination_bytes,
                _RENAME_EXCL,
            )
        elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
            rename = library.renameat2
            rename.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            rename.restype = ctypes.c_int
            result = rename(
                parent,
                source_bytes,
                parent,
                destination_bytes,
                _RENAME_NOREPLACE,
            )
        else:
            raise errors.PathSafetyError(
                "atomic no-replace directory creation is unavailable"
            )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination)
        raise OSError(error_number, os.strerror(error_number), destination)

    @classmethod
    def create_directory_entry(
        cls,
        *,
        parent: int,
        leaf: str,
        label: str,
    ) -> tuple[int, os.stat_result]:
        """Atomically claim a new directory name without replacement."""
        temporary = f".koios-dir-{secrets.token_hex(16)}.tmp"
        descriptor = -1
        renamed = False
        try:
            os.mkdir(temporary, mode=0o700, dir_fd=parent)
            descriptor = os.open(
                temporary,
                _DIRECTORY_FLAGS,
                dir_fd=parent,
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise errors.PathSafetyError(
                    f"cannot create directory for {label}"
                )
            cls._rename_directory_no_replace(
                parent=parent,
                source=temporary,
                destination=leaf,
            )
            renamed = True
            os.fsync(parent)
            return descriptor, metadata
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            if not renamed:
                try:
                    os.rmdir(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
            raise

    @staticmethod
    def open_anonymous_file(*, parent: int, label: str) -> int:
        """Open an unlinked regular file for descriptor-bound publication."""
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        if sys.platform.startswith("linux") and hasattr(os, "O_TMPFILE"):
            try:
                descriptor = os.open(
                    ".",
                    flags | os.O_TMPFILE,
                    0o600,
                    dir_fd=parent,
                )
            except OSError as error:
                raise errors.PathSafetyError(
                    f"anonymous publication is unavailable for {label}"
                ) from error
            if os.fstat(descriptor).st_nlink != 0:
                os.close(descriptor)
                raise errors.PathSafetyError(
                    f"publication staging is not anonymous for {label}"
                )
            return descriptor
        if sys.platform == "darwin":
            temporary = f".koios-file-{secrets.token_hex(16)}.tmp"
            descriptor = -1
            try:
                descriptor = os.open(
                    temporary,
                    flags
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent,
                )
                os.unlink(temporary, dir_fd=parent)
                if os.fstat(descriptor).st_nlink != 0:
                    raise errors.PathSafetyError(
                        f"publication staging is not anonymous for {label}"
                    )
                return descriptor
            except BaseException:
                if descriptor >= 0:
                    os.close(descriptor)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                raise
        raise errors.PathSafetyError(
            f"descriptor-bound publication is unavailable for {label}"
        )

    @staticmethod
    def publish_open_file_no_replace(
        *,
        parent: int,
        descriptor: int,
        destination: str,
    ) -> None:
        """Publish one open file without a mutable source pathname."""
        if os.fstat(descriptor).st_nlink != 0:
            raise errors.PathSafetyError(
                "publication source descriptor is not anonymous"
            )
        library = ctypes.CDLL(None, use_errno=True)
        destination_bytes = os.fsencode(destination)
        ctypes.set_errno(0)
        if sys.platform.startswith("linux") and hasattr(library, "linkat"):
            link = library.linkat
            link.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
            )
            link.restype = ctypes.c_int
            source = os.fsencode(f"/proc/self/fd/{descriptor}")
            result = link(
                -100,
                source,
                parent,
                destination_bytes,
                0x400,
            )
        elif sys.platform == "darwin" and hasattr(library, "fclonefileat"):
            clone = library.fclonefileat
            clone.argtypes = (
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
            )
            clone.restype = ctypes.c_int
            result = clone(descriptor, parent, destination_bytes, 0)
        else:
            raise errors.PathSafetyError(
                "descriptor-bound no-replace file publication is unavailable"
            )
        if result == 0:
            os.fsync(parent)
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(destination)
        raise OSError(error_number, os.strerror(error_number), destination)

    @staticmethod
    def file_identity(
        *,
        metadata: os.stat_result,
    ) -> tuple[int, int, int, int, int]:
        """Return the stable fields checked around a descriptor operation."""
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    @staticmethod
    def open_directory(*, path: Path, label: str) -> int:
        """Open a directory without following its final path component."""
        try:
            descriptor = os.open(path, _DIRECTORY_FLAGS)
        except OSError as error:
            DescriptorFilesystem.raise_path_error(
                error=error,
                message=f"cannot safely open {label}",
            )
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            raise errors.PathSafetyError(f"{label} must be a directory")
        return descriptor

    @staticmethod
    def raise_path_error(*, error: OSError, message: str) -> Never:
        """Translate platform path failures into stable path-safety errors."""
        if error.errno in {
            errno.ELOOP,
            errno.ENOTDIR,
            errno.EPERM,
            errno.EINVAL,
        }:
            raise errors.PathSafetyError(message) from error
        raise error
