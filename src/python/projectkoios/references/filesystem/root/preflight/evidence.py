from __future__ import annotations

from dataclasses import dataclass
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.filesystem.path.validation import (
    validate_root_alias,
)

from .identity import validate_probe_id
from .storage import RootStorageClass
from .support import PlaceholderProbeSupport


@final
@dataclass(frozen=True, slots=True)
class RootPreflightEvidence(DataObjectModel):
    """Privacy-reduced evidence for one declared root capability."""

    root_alias: str
    storage_class: RootStorageClass
    probe_id: str
    probe_support: PlaceholderProbeSupport | None

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        validate_probe_id(self.probe_id)
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("root storage class must be explicit")
        if self.probe_support is not None and not isinstance(
            self.probe_support, PlaceholderProbeSupport
        ):
            raise ValueError("placeholder probe support is invalid")
        if self.storage_class is RootStorageClass.LOCAL:
            if self.probe_support is not None:
                raise ValueError("local roots cannot claim cloud-probe support")
        elif self.probe_support is None:
            raise ValueError(
                "cloud-backed roots require probe support evidence"
            )
