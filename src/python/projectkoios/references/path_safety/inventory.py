"""Immutable observations from bounded filesystem inventories."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.path_safety import validation


@final
@dataclass(frozen=True, slots=True)
class FileObservation(DataObjectModel):
    """One streaming observation of a confined regular file."""

    byte_size: int
    sha256: str
    prefix: bytes


class FilesystemIssueKind(StrEnum):
    """Typed metadata-only outcomes from a bounded directory inventory."""

    ACCESS_CONTROLLED = "access-controlled"
    UNREADABLE = "unreadable"
    SYMLINK = "symlink"
    UNSUPPORTED_OBJECT = "unsupported-object"
    FILESYSTEM_BOUNDARY = "filesystem-boundary"
    NONPORTABLE_NAME = "nonportable-name"
    ENTRY_LIMIT = "entry-limit"
    FILE_LIMIT = "file-limit"
    DEPTH_LIMIT = "depth-limit"


@final
@dataclass(frozen=True, slots=True)
class FilesystemInventoryIssue(DataObjectModel):
    """One typed issue from a metadata-only directory inventory."""

    relative_path: PurePosixPath | None
    kind: FilesystemIssueKind
    limit_name: str | None = None
    limit: int | None = None
    observed: int | None = None

    def __post_init__(self) -> None:
        if self.relative_path is not None:
            validation.validate_relative_path(self.relative_path)
        if not isinstance(self.kind, FilesystemIssueKind):
            raise ValueError("filesystem inventory issue kind is invalid")
        limit_kinds = {
            FilesystemIssueKind.ENTRY_LIMIT: "max_entries",
            FilesystemIssueKind.FILE_LIMIT: "max_files",
            FilesystemIssueKind.DEPTH_LIMIT: "max_depth",
        }
        expected_name = limit_kinds.get(self.kind)
        if expected_name is None:
            if any(
                value is not None
                for value in (self.limit_name, self.limit, self.observed)
            ):
                raise ValueError("non-limit inventory issue carries a limit")
        elif (
            self.limit_name != expected_name
            or type(self.limit) is not int
            or type(self.observed) is not int
            or self.limit <= 0
            or self.observed <= self.limit
        ):
            raise ValueError("filesystem inventory limit issue is invalid")

    @property
    def sort_key(self) -> tuple[str, str, str, int, int]:
        """Return the canonical ordering key for this issue."""
        return (
            "" if self.relative_path is None else self.relative_path.as_posix(),
            self.kind.value,
            self.limit_name or "",
            self.limit or 0,
            self.observed or 0,
        )


@final
@dataclass(frozen=True, slots=True)
class FilesystemInventory(DataObjectModel):
    """One canonical bounded inventory and its typed incompleteness."""

    files: tuple[PurePosixPath, ...]
    issues: tuple[FilesystemInventoryIssue, ...]
    entries_seen: int

    def __post_init__(self) -> None:
        if tuple(sorted(self.files, key=lambda item: item.as_posix())) != (
            self.files
        ) or len(self.files) != len(set(self.files)):
            raise ValueError("filesystem inventory files are not canonical")
        issue_keys = tuple(item.sort_key for item in self.issues)
        if issue_keys != tuple(sorted(issue_keys)) or len(issue_keys) != len(
            set(issue_keys)
        ):
            raise ValueError("filesystem inventory issues are not canonical")
        if type(self.entries_seen) is not int or self.entries_seen < 0:
            raise ValueError("filesystem inventory entry count is invalid")

    @property
    def limit_exceeded(self) -> bool:
        """Return whether any bounded inventory limit was exceeded."""
        return any(
            item.kind
            in {
                FilesystemIssueKind.ENTRY_LIMIT,
                FilesystemIssueKind.FILE_LIMIT,
                FilesystemIssueKind.DEPTH_LIMIT,
            }
            for item in self.issues
        )
