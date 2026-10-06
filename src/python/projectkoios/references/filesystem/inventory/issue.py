from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.filesystem.path.validation import (
    validate_relative_path,
)

from .status import FilesystemIssueKind


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
            validate_relative_path(self.relative_path)
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
        return (
            "" if self.relative_path is None else self.relative_path.as_posix(),
            self.kind.value,
            self.limit_name or "",
            self.limit or 0,
            self.observed or 0,
        )
