from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import final

from projectkoios.base import DataObjectModel

from .issue import FilesystemInventoryIssue
from .status import FilesystemIssueKind


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
        return any(
            item.kind
            in {
                FilesystemIssueKind.ENTRY_LIMIT,
                FilesystemIssueKind.FILE_LIMIT,
                FilesystemIssueKind.DEPTH_LIMIT,
            }
            for item in self.issues
        )
