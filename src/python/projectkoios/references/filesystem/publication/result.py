from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class AddressedFilePublication:
    """Describe one verified content-addressed file publication."""

    path: Path
    sha256: str
    byte_size: int
    created: bool
