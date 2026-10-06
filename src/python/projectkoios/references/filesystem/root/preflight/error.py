from __future__ import annotations

import json

from projectkoios.references.filesystem.operation.error import (
    FilesystemOperationError,
)

from .observation import PlaceholderObservation


class PlaceholderPreflightError(FilesystemOperationError):
    """Raised when cloud-placeholder safety cannot permit byte access."""

    code = "placeholder-preflight-incomplete"
    coverage_status = "incomplete"

    def __init__(self, observation: PlaceholderObservation) -> None:
        self.observation = observation
        super().__init__(
            "cloud-placeholder preflight refused access: "
            f"{observation.root_alias}/"
            f"{observation.relative_path or '<root>'} "
            f"is {observation.status.value}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "coverage_status": self.coverage_status,
            "root_alias": self.observation.root_alias,
            "relative_path": self.observation.relative_path,
            "storage_class": self.observation.storage_class.value,
            "probe_id": self.observation.probe_id,
            "status": self.observation.status.value,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
