from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectkoios.references.citation.key.validation import validate_citekey
from projectkoios.references.filesystem.root.preflight.probe import (
    RootPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)


@dataclass(frozen=True, slots=True)
class ReferenceEvidenceInput:
    citekey: str
    path: Path
    storage_class: RootStorageClass
    placeholder_probe: RootPlaceholderProbe | None = None

    def __post_init__(self) -> None:
        validate_citekey(self.citekey, field="reference-evidence citekey")
        if not isinstance(self.path, Path):
            raise TypeError("reference-evidence path must be a Path")
        if not isinstance(self.storage_class, RootStorageClass):
            raise TypeError("reference-evidence storage class must be explicit")
