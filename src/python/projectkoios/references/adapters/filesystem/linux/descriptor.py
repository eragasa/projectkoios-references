from __future__ import annotations

import ctypes
import errno
import os

from projectkoios.references.filesystem.descriptor.error import (
    FilesystemDescriptorError,
)

_RENAME_NOREPLACE = 1


def mount_identity(*, descriptor: int) -> int | None:
    try:
        with open(
            f"/proc/self/fdinfo/{descriptor}", encoding="utf-8"
        ) as stream:
            for line in stream:
                name, separator, value = line.partition(":")
                if separator and name == "mnt_id":
                    rendered = value.strip()
                    return int(rendered) if rendered.isascii() else None
    except OSError, ValueError:
        return None
    return None


def rename_directory_no_replace(
    *, parent: int, source: str, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if not hasattr(library, "renameat2"):
        raise FilesystemDescriptorError(
            "atomic no-replace directory creation is unavailable"
        )
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
        os.fsencode(source),
        parent,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def open_anonymous_file(*, parent: int, label: str) -> int:
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_TMPFILE"):
        raise FilesystemDescriptorError(
            f"anonymous publication is unavailable for {label}"
        )
    try:
        descriptor = os.open(".", flags | os.O_TMPFILE, 384, dir_fd=parent)
    except OSError as error:
        raise FilesystemDescriptorError(
            f"anonymous publication is unavailable for {label}"
        ) from error
    if os.fstat(descriptor).st_nlink != 0:
        os.close(descriptor)
        raise FilesystemDescriptorError(
            f"publication staging is not anonymous for {label}"
        )
    return descriptor


def publish_open_file_no_replace(
    *, parent: int, descriptor: int, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if not hasattr(library, "linkat"):
        raise FilesystemDescriptorError(
            "descriptor-bound no-replace file publication is unavailable"
        )
    link = library.linkat
    link.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    )
    link.restype = ctypes.c_int
    result = link(
        -100,
        os.fsencode(f"/proc/self/fd/{descriptor}"),
        parent,
        os.fsencode(destination),
        1024,
    )
    if result == 0:
        os.fsync(parent)
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(destination)
    raise OSError(error_number, os.strerror(error_number), destination)
