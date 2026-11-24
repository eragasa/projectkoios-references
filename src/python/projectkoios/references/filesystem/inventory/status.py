from __future__ import annotations

from enum import StrEnum


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
