from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CITEKEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ReferenceFilenames:
    """Portable filenames derived from one canonical citation key."""

    citekey: str
    note: Path
    pdf: Path

    @classmethod
    def from_citekey(cls, citekey: str) -> ReferenceFilenames:
        """Create the note and PDF filenames for a citation key."""
        if not _CITEKEY_PATTERN.fullmatch(citekey):
            raise ValueError(
                "citekey must start with a letter and contain only letters, "
                "numbers, period, underscore, or hyphen"
            )
        return cls(
            citekey=citekey,
            note=Path(f"{citekey}.md"),
            pdf=Path(f"{citekey}.pdf"),
        )
