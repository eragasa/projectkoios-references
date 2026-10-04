"""Bounded directory scanning through authorized-root descriptors."""

from __future__ import annotations

import errno
import os
from pathlib import PurePosixPath

from projectkoios.references.path_safety import (
    errors,
    inventory,
    platform,
    validation,
)
from projectkoios.references.path_safety.authorization import (
    AuthorizedRootIdentity,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_MAX_DIRECTORY_ENTRIES = 100_000
_MAX_DIRECTORY_DEPTH = 128


class AuthorizedRootScanning(AuthorizedRootIdentity):
    """Own bounded deterministic traversal for an authorized root."""

    __slots__ = ()

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

    def inventory_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        max_files: int,
        max_entries: int,
        max_depth: int,
        case_sensitive_suffix: bool = True,
    ) -> inventory.FilesystemInventory:
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
        issues: list[inventory.FilesystemInventoryIssue] = []
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
        return inventory.FilesystemInventory(
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
        issues: list[inventory.FilesystemInventoryIssue],
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
                            inventory.FilesystemInventoryIssue(
                                current,
                                inventory.FilesystemIssueKind.ENTRY_LIMIT,
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
                inventory.FilesystemInventoryIssue(
                    current,
                    inventory.FilesystemIssueKind.ACCESS_CONTROLLED,
                )
            )
            return
        except OSError:
            issues.append(
                inventory.FilesystemInventoryIssue(
                    current,
                    inventory.FilesystemIssueKind.UNREADABLE,
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
            except errors.PathSafetyError:
                issues.append(
                    inventory.FilesystemInventoryIssue(
                        current,
                        inventory.FilesystemIssueKind.NONPORTABLE_NAME,
                    )
                )
                continue
            try:
                if entry.is_symlink():
                    issues.append(
                        inventory.FilesystemInventoryIssue(
                            relative,
                            inventory.FilesystemIssueKind.SYMLINK,
                        )
                    )
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not recursive:
                        continue
                    if len(relative.parts) > max_depth:
                        issues.append(
                            inventory.FilesystemInventoryIssue(
                                relative,
                                inventory.FilesystemIssueKind.DEPTH_LIMIT,
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
                            inventory.FilesystemInventoryIssue(
                                relative,
                                inventory.FilesystemIssueKind.ACCESS_CONTROLLED,
                            )
                        )
                        continue
                    except OSError as error:
                        kind = (
                            inventory.FilesystemIssueKind.SYMLINK
                            if error.errno == errno.ELOOP
                            else inventory.FilesystemIssueKind.UNREADABLE
                        )
                        issues.append(
                            inventory.FilesystemInventoryIssue(relative, kind)
                        )
                        continue
                    try:
                        child_metadata = os.fstat(child)
                    except OSError:
                        os.close(child)
                        issues.append(
                            inventory.FilesystemInventoryIssue(
                                relative,
                                inventory.FilesystemIssueKind.UNREADABLE,
                            )
                        )
                        continue
                    if child_metadata.st_dev != self.device:
                        os.close(child)
                        issues.append(
                            inventory.FilesystemInventoryIssue(
                                relative,
                                inventory.FilesystemIssueKind.FILESYSTEM_BOUNDARY,
                            )
                        )
                        continue
                    try:
                        self._require_mount_identity(child, safe=relative)
                    except errors.FilesystemBoundaryError:
                        os.close(child)
                        issues.append(
                            inventory.FilesystemInventoryIssue(
                                relative,
                                inventory.FilesystemIssueKind.FILESYSTEM_BOUNDARY,
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
                                inventory.FilesystemInventoryIssue(
                                    relative,
                                    inventory.FilesystemIssueKind.FILE_LIMIT,
                                    "max_files",
                                    max_files,
                                    len(found),
                                )
                            )
                            abort[0] = True
                            return
                    continue
                issues.append(
                    inventory.FilesystemInventoryIssue(
                        relative,
                        inventory.FilesystemIssueKind.UNSUPPORTED_OBJECT,
                    )
                )
            except PermissionError:
                issues.append(
                    inventory.FilesystemInventoryIssue(
                        relative,
                        inventory.FilesystemIssueKind.ACCESS_CONTROLLED,
                    )
                )
            except OSError:
                issues.append(
                    inventory.FilesystemInventoryIssue(
                        relative,
                        inventory.FilesystemIssueKind.UNREADABLE,
                    )
                )

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
            raise errors.PathLimitError(
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
                    raise errors.PathLimitError(
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
                raise errors.PathSafetyError(
                    f"{self.label} contains a symlink: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                if not recursive:
                    if reject_directories:
                        raise errors.PathSafetyError(
                            f"{self.label} contains an unexpected directory: "
                            f"{relative}"
                        )
                    continue
                try:
                    child = os.open(
                        entry.name, _DIRECTORY_FLAGS, dir_fd=descriptor
                    )
                except OSError as error:
                    platform.DescriptorFilesystem.raise_path_error(
                        error=error,
                        message=(
                            f"cannot safely traverse {self.label}: {relative}"
                        ),
                    )
                try:
                    child_metadata = os.fstat(child)
                except OSError as error:
                    os.close(child)
                    raise errors.PathSafetyError(
                        f"cannot classify filesystem boundary in "
                        f"{self.label}: {relative}"
                    ) from error
                if child_metadata.st_dev != self.device:
                    os.close(child)
                    raise errors.PathSafetyError(
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
                        raise errors.PathLimitError(
                            resource=self.label,
                            limit_name="max_files",
                            limit=max_files,
                            observed=len(found),
                        )
                continue
            raise errors.PathSafetyError(
                f"{self.label} contains an unsupported filesystem object: "
                f"{relative}"
            )
