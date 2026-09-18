from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectkoios.references.path_safety import validate_citekey


@dataclass(frozen=True)
class ReferenceFilenames:
    """Portable filenames derived from one canonical citation key."""

    citekey: str
    note: Path
    pdf: Path

    @classmethod
    def from_citekey(cls, citekey: str) -> ReferenceFilenames:
        """Create the note and PDF filenames for a citation key."""
        safe_citekey = validate_citekey(citekey)
        return cls(
            citekey=safe_citekey,
            note=Path(f"{safe_citekey}.md"),
            pdf=Path(f"{safe_citekey}.pdf"),
        )
