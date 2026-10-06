from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class FilesystemObservationError(FilesystemOperationError):
    """Reject an unsafe or unstable filesystem observation."""
