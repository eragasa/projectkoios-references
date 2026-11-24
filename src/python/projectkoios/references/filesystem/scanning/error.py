from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class FilesystemScanningError(FilesystemOperationError):
    """Reject unsafe or incomplete filesystem traversal."""
