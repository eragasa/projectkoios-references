from __future__ import annotations

from dataclasses import dataclass
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.filesystem.path.validation import (
    validate_relative_path,
    validate_root_alias,
)

from .identity import validate_probe_id
from .status import PlaceholderStatus
from .storage import RootStorageClass


@final
@dataclass(frozen=True, slots=True)
class PlaceholderObservation(DataObjectModel):
    """A privacy-reduced, metadata-only candidate-path observation."""

    root_alias: str
    relative_path: str | None
    storage_class: RootStorageClass
    probe_id: str
    status: PlaceholderStatus

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        validate_probe_id(self.probe_id)
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("root storage class must be explicit")
        if not isinstance(self.status, PlaceholderStatus):
            raise ValueError("placeholder status is invalid")
        if self.relative_path is not None:
            validate_relative_path(self.relative_path)
        if self.storage_class is RootStorageClass.LOCAL and self.status in {
            PlaceholderStatus.CLOUD_PLACEHOLDER,
            PlaceholderStatus.UNSUPPORTED_PLATFORM,
        }:
            raise ValueError(
                "local roots cannot report cloud-placeholder probe states"
            )
