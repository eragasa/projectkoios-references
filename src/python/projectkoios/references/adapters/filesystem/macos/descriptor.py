from __future__ import annotations

import ctypes
import errno
import os
import secrets

from projectkoios.references.filesystem.descriptor.error import (
    FilesystemDescriptorError,
)

_RENAME_EXCL = 4


def rename_directory_no_replace(
    *, parent: int, source: str, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
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
        os.fsencode(source),
        parent,
        os.fsencode(destination),
        _RENAME_EXCL,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def open_anonymous_file(*, parent: int, label: str) -> int:
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    temporary = f".koios-file-{secrets.token_hex(16)}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            flags | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            384,
            dir_fd=parent,
        )
        os.unlink(temporary, dir_fd=parent)
        if os.fstat(descriptor).st_nlink != 0:
            raise FilesystemDescriptorError(
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


def publish_open_file_no_replace(
    *, parent: int, descriptor: int, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if not hasattr(library, "fclonefileat"):
        raise FilesystemDescriptorError(
            "descriptor-bound no-replace file publication is unavailable"
        )
    clone = library.fclonefileat
    clone.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
    clone.restype = ctypes.c_int
    result = clone(descriptor, parent, os.fsencode(destination), 0)
    if result == 0:
        os.fsync(parent)
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(destination)
    raise OSError(error_number, os.strerror(error_number), destination)
