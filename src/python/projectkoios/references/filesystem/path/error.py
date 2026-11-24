from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class FilesystemPathError(FilesystemOperationError):
    """Reject a nonportable or escaping filesystem path component."""
