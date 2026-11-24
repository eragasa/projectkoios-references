from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class CloudRootMutationError(FilesystemOperationError):
    """Reject mutation of a cloud-backed root without external authority."""

    code = "cloud-root-mutation-forbidden"
