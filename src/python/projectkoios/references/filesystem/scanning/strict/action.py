from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import final

from projectkoios.references.filesystem.descriptor import capability as platform
from projectkoios.references.filesystem.limit.error import FilesystemLimitError
from projectkoios.references.filesystem.root.descriptor import RootDescriptor
from projectkoios.references.filesystem.scanning.error import (
    FilesystemScanningError,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_MAX_DIRECTORY_ENTRIES = 100_000
_MAX_DIRECTORY_DEPTH = 128


@final
@dataclass(frozen=True, slots=True, eq=False)
class StrictFileScanner:
    """Strict bounded listing that fails on unsafe or partial traversal."""

    _descriptor: RootDescriptor

    @property
    def label(self) -> str:
        return self._descriptor.label

    @property
    def device(self) -> int:
        return self._descriptor.device

    def _open_root(self) -> int:
        return self._descriptor._open_root()

    def _require_mount_identity(
        self, descriptor: int, *, safe: PurePosixPath
    ) -> None:
        self._descriptor._require_mount_identity(descriptor, safe=safe)

    def iter_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        reject_directories: bool = False,
        max_files: int | None = None,
        max_entries: int | None = None,
        max_depth: int | None = None,
    ) -> tuple[PurePosixPath, ...]:
        """List regular files deterministically without following symlinks."""
        for name, value in (
            ("max_files", max_files),
            ("max_entries", max_entries),
            ("max_depth", max_depth),
        ):
            ceiling = (
                _MAX_DIRECTORY_DEPTH
                if name == "max_depth"
                else _MAX_DIRECTORY_ENTRIES
            )
            if value is not None and not 0 < value <= ceiling:
                raise ValueError(
                    f"{name} must be positive, no greater than {ceiling}, "
                    "or null"
                )
        max_files = _MAX_DIRECTORY_ENTRIES if max_files is None else max_files
        max_entries = (
            _MAX_DIRECTORY_ENTRIES if max_entries is None else max_entries
        )
        max_depth = _MAX_DIRECTORY_DEPTH if max_depth is None else max_depth
        root = self._open_root()
        try:
            found: list[PurePosixPath] = []
            entries_seen = [0]
            self._walk(
                root,
                prefix=(),
                suffix=suffix,
                recursive=recursive,
                reject_directories=reject_directories,
                found=found,
                entries_seen=entries_seen,
                max_files=max_files,
                max_entries=max_entries,
                max_depth=max_depth,
            )
        finally:
            os.close(root)
        return tuple(sorted(found, key=lambda item: item.as_posix()))

    def _walk(
        self,
        descriptor: int,
        *,
        prefix: tuple[str, ...],
        suffix: str,
        recursive: bool,
        reject_directories: bool,
        found: list[PurePosixPath],
        entries_seen: list[int],
        max_files: int | None,
        max_entries: int | None,
        max_depth: int | None,
    ) -> None:
        if max_depth is not None and len(prefix) > max_depth:
            raise FilesystemLimitError(
                resource=self.label,
                limit_name="max_depth",
                limit=max_depth,
                observed=len(prefix),
            )
        ordered: list[os.DirEntry[str]] = []
        with os.scandir(descriptor) as entries:
            for entry in entries:
                entries_seen[0] += 1
                if max_entries is not None and entries_seen[0] > max_entries:
                    raise FilesystemLimitError(
                        resource=self.label,
                        limit_name="max_entries",
                        limit=max_entries,
                        observed=entries_seen[0],
                    )
                ordered.append(entry)
        ordered.sort(key=lambda item: item.name)
        for entry in ordered:
            relative = PurePosixPath(*prefix, entry.name)
            if entry.is_symlink():
                raise FilesystemScanningError(
                    f"{self.label} contains a symlink: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                if not recursive:
                    if reject_directories:
                        raise FilesystemScanningError(
                            f"{self.label} contains an unexpected directory: "
                            f"{relative}"
                        )
                    continue
                try:
                    child = os.open(
                        entry.name, _DIRECTORY_FLAGS, dir_fd=descriptor
                    )
                except OSError as error:
                    platform.raise_path_error(
                        error=error,
                        message=(
                            f"cannot safely traverse {self.label}: {relative}"
                        ),
                    )
                try:
                    child_metadata = os.fstat(child)
                except OSError as error:
                    os.close(child)
                    raise FilesystemScanningError(
                        f"cannot classify filesystem boundary in "
                        f"{self.label}: {relative}"
                    ) from error
                if child_metadata.st_dev != self.device:
                    os.close(child)
                    raise FilesystemScanningError(
                        f"{self.label} crosses a filesystem boundary: "
                        f"{relative}"
                    )
                try:
                    self._require_mount_identity(child, safe=relative)
                except BaseException:
                    os.close(child)
                    raise
                try:
                    self._walk(
                        child,
                        prefix=(*prefix, entry.name),
                        suffix=suffix,
                        recursive=True,
                        reject_directories=reject_directories,
                        found=found,
                        entries_seen=entries_seen,
                        max_files=max_files,
                        max_entries=max_entries,
                        max_depth=max_depth,
                    )
                finally:
                    os.close(child)
                continue
            if entry.is_file(follow_symlinks=False):
                if entry.name.endswith(suffix):
                    found.append(relative)
                    if max_files is not None and len(found) > max_files:
                        raise FilesystemLimitError(
                            resource=self.label,
                            limit_name="max_files",
                            limit=max_files,
                            observed=len(found),
                        )
                continue
            raise FilesystemScanningError(
                f"{self.label} contains an unsupported filesystem object: "
                f"{relative}"
            )
