from __future__ import annotations

from enum import StrEnum


class PlaceholderStatus(StrEnum):
    """A metadata-only classification made before candidate byte access."""

    ORDINARY_FILE = "ordinary-file"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    MISSING = "missing"
    ACCESS_CONTROLLED = "access-controlled"
    UNREADABLE = "unreadable"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    AMBIGUOUS = "ambiguous"
    FILESYSTEM_BOUNDARY = "filesystem-boundary"
