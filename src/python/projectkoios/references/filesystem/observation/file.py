from __future__ import annotations

from dataclasses import dataclass
from typing import final

from projectkoios.base import DataObjectModel


@final
@dataclass(frozen=True, slots=True)
class FileObservation(DataObjectModel):
    """One streaming observation of a confined regular file."""

    byte_size: int
    sha256: str
    prefix: bytes
