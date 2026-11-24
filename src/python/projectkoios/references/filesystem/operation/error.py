from __future__ import annotations


class FilesystemOperationError(ValueError):
    """Base failure for a descriptor-confined filesystem operation."""
