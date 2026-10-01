"""Typed failures for confined filesystem operations."""

from __future__ import annotations


class PathSafetyError(ValueError):
    """Raised when a path cannot be used within an authorized root."""


class CloudRootMutationError(PathSafetyError):
    """Raised before attempting mutation of a cloud-backed root."""

    code = "cloud-root-mutation-forbidden"


class FilesystemBoundaryError(PathSafetyError):
    """Raised when a confined operation would cross the root filesystem."""

    code = "filesystem-boundary"


class PathLimitError(PathSafetyError):
    """Raised before a bounded filesystem observation can become partial."""

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
