from __future__ import annotations

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)


class FilesystemLimitError(FilesystemOperationError):
    """Refuse an operation before bounded coverage becomes partial."""

    coverage_status = "incomplete"

    def __init__(
        self,
        *,
        resource: str,
        limit_name: str,
        limit: int,
        observed: int,
    ) -> None:
        self.resource = resource
        self.limit_name = limit_name
        self.limit = limit
        self.observed = observed
        super().__init__(
            f"{resource} exceeds {limit_name}: observed {observed}, "
            f"limit {limit}; coverage remains incomplete"
        )
