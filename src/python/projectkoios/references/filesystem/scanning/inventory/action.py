from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import final

from projectkoios.references.filesystem.descriptor.error import (
    FilesystemBoundaryError,
)
from projectkoios.references.filesystem.inventory.issue import (
    FilesystemInventoryIssue,
)
from projectkoios.references.filesystem.inventory.result import (
    FilesystemInventory,
)
from projectkoios.references.filesystem.inventory.status import (
    FilesystemIssueKind,
)
from projectkoios.references.filesystem.path import validation
from projectkoios.references.filesystem.path.error import FilesystemPathError
from projectkoios.references.filesystem.root.descriptor import RootDescriptor

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
class InventoryScanner:
    """Bounded traversal retaining typed incompleteness evidence."""

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

    def inventory_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        max_files: int,
        max_entries: int,
        max_depth: int,
        case_sensitive_suffix: bool = True,
    ) -> FilesystemInventory:
        """Inventory names and typed skips without following symlinks.

        Unlike :meth:`iter_files`, this API retains inaccessible, symlinked,
        unsupported, and depth-limited objects as observations so a caller can
        publish explicitly incomplete coverage.  Entry and file-count limits
        stop the inventory before candidate bytes are accessed.
        """
        if not suffix or not isinstance(suffix, str):
            raise ValueError("inventory suffix must be a non-empty string")
        if type(case_sensitive_suffix) is not bool:
            raise ValueError("case_sensitive_suffix must be a bool")
        for name, value, ceiling in (
            ("max_files", max_files, _MAX_DIRECTORY_ENTRIES),
            ("max_entries", max_entries, _MAX_DIRECTORY_ENTRIES),
            ("max_depth", max_depth, _MAX_DIRECTORY_DEPTH),
        ):
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError(
                    f"{name} must be positive and no greater than {ceiling}"
                )
        root = self._open_root()
        found: list[PurePosixPath] = []
        issues: list[FilesystemInventoryIssue] = []
        entries_seen = [0]
        abort = [False]
        try:
            self._walk_inventory(
                root,
                prefix=(),
                suffix=suffix,
                recursive=recursive,
                case_sensitive_suffix=case_sensitive_suffix,
                found=found,
                issues=issues,
                entries_seen=entries_seen,
                abort=abort,
                max_files=max_files,
                max_entries=max_entries,
                max_depth=max_depth,
            )
        finally:
            os.close(root)
        ordered_issues = tuple(
            sorted(set(issues), key=lambda issue: issue.sort_key)
        )
        ordered_files = (
            ()
            if abort[0]
            else tuple(sorted(set(found), key=lambda item: item.as_posix()))
        )
        return FilesystemInventory(
            files=ordered_files,
            issues=ordered_issues,
            entries_seen=entries_seen[0],
        )

    def _walk_inventory(
        self,
        descriptor: int,
        *,
        prefix: tuple[str, ...],
        suffix: str,
        recursive: bool,
        case_sensitive_suffix: bool,
        found: list[PurePosixPath],
        issues: list[FilesystemInventoryIssue],
        entries_seen: list[int],
        abort: list[bool],
        max_files: int,
        max_entries: int,
        max_depth: int,
    ) -> None:
        if abort[0]:
            return
        current = PurePosixPath(*prefix) if prefix else None
        try:
            ordered: list[os.DirEntry[str]] = []
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    entries_seen[0] += 1
                    if entries_seen[0] > max_entries:
                        issues.append(
                            FilesystemInventoryIssue(
                                current,
                                FilesystemIssueKind.ENTRY_LIMIT,
                                "max_entries",
                                max_entries,
                                entries_seen[0],
                            )
                        )
                        abort[0] = True
                        return
                    ordered.append(entry)
        except PermissionError:
            issues.append(
                FilesystemInventoryIssue(
                    current,
                    FilesystemIssueKind.ACCESS_CONTROLLED,
                )
            )
            return
        except OSError:
            issues.append(
                FilesystemInventoryIssue(
                    current,
                    FilesystemIssueKind.UNREADABLE,
                )
            )
            return
        ordered.sort(key=lambda item: item.name)
        expected_suffix = suffix if case_sensitive_suffix else suffix.casefold()
        for entry in ordered:
            if abort[0]:
                return
            relative = PurePosixPath(*prefix, entry.name)
            try:
                validation.validate_relative_path(relative)
            except FilesystemPathError:
                issues.append(
                    FilesystemInventoryIssue(
                        current,
                        FilesystemIssueKind.NONPORTABLE_NAME,
                    )
                )
                continue
            try:
                if entry.is_symlink():
                    issues.append(
                        FilesystemInventoryIssue(
                            relative,
                            FilesystemIssueKind.SYMLINK,
                        )
                    )
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not recursive:
                        continue
                    if len(relative.parts) > max_depth:
                        issues.append(
                            FilesystemInventoryIssue(
                                relative,
                                FilesystemIssueKind.DEPTH_LIMIT,
                                "max_depth",
                                max_depth,
                                len(relative.parts),
                            )
                        )
                        continue
                    try:
                        child = os.open(
                            entry.name,
                            _DIRECTORY_FLAGS,
                            dir_fd=descriptor,
                        )
                    except PermissionError:
                        issues.append(
                            FilesystemInventoryIssue(
                                relative,
                                FilesystemIssueKind.ACCESS_CONTROLLED,
                            )
                        )
                        continue
                    except OSError as error:
                        kind = (
                            FilesystemIssueKind.SYMLINK
                            if error.errno == errno.ELOOP
                            else FilesystemIssueKind.UNREADABLE
                        )
                        issues.append(FilesystemInventoryIssue(relative, kind))
                        continue
                    try:
                        child_metadata = os.fstat(child)
                    except OSError:
                        os.close(child)
                        issues.append(
                            FilesystemInventoryIssue(
                                relative,
                                FilesystemIssueKind.UNREADABLE,
                            )
                        )
                        continue
                    if child_metadata.st_dev != self.device:
                        os.close(child)
                        issues.append(
                            FilesystemInventoryIssue(
                                relative,
                                FilesystemIssueKind.FILESYSTEM_BOUNDARY,
                            )
                        )
                        continue
                    try:
                        self._require_mount_identity(child, safe=relative)
                    except FilesystemBoundaryError:
                        os.close(child)
                        issues.append(
                            FilesystemInventoryIssue(
                                relative,
                                FilesystemIssueKind.FILESYSTEM_BOUNDARY,
                            )
                        )
                        continue
                    try:
                        self._walk_inventory(
                            child,
                            prefix=(*prefix, entry.name),
                            suffix=suffix,
                            recursive=True,
                            case_sensitive_suffix=case_sensitive_suffix,
                            found=found,
                            issues=issues,
                            entries_seen=entries_seen,
                            abort=abort,
                            max_files=max_files,
                            max_entries=max_entries,
                            max_depth=max_depth,
                        )
                    finally:
                        os.close(child)
                    continue
                if entry.is_file(follow_symlinks=False):
                    name = (
                        entry.name
                        if case_sensitive_suffix
                        else entry.name.casefold()
                    )
                    if name.endswith(expected_suffix):
                        found.append(relative)
                        if len(found) > max_files:
                            issues.append(
                                FilesystemInventoryIssue(
                                    relative,
                                    FilesystemIssueKind.FILE_LIMIT,
                                    "max_files",
                                    max_files,
                                    len(found),
                                )
                            )
                            abort[0] = True
                            return
                    continue
                issues.append(
                    FilesystemInventoryIssue(
                        relative,
                        FilesystemIssueKind.UNSUPPORTED_OBJECT,
                    )
                )
            except PermissionError:
                issues.append(
                    FilesystemInventoryIssue(
                        relative,
                        FilesystemIssueKind.ACCESS_CONTROLLED,
                    )
                )
            except OSError:
                issues.append(
                    FilesystemInventoryIssue(
                        relative,
                        FilesystemIssueKind.UNREADABLE,
                    )
                )
