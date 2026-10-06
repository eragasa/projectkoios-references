from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class FilesystemPublicationError(FilesystemOperationError):
    """Reject unsafe, replacing, or unverifiable filesystem publication."""
