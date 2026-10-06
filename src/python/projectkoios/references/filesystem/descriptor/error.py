from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class FilesystemDescriptorError(FilesystemOperationError):
    """Reject unsafe descriptor traversal or a changed filesystem object."""


class FilesystemBoundaryError(FilesystemDescriptorError):
    """Reject crossing the authorized root filesystem or mount."""

    code = "filesystem-boundary"
