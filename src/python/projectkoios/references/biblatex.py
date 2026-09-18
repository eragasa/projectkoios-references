from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projectkoios.references.models import (
    BibliographyOccurrence,
    ReferenceRecord,
    normalize_doi,
)
from projectkoios.references.path_safety import read_path_text


class BibLaTeXUnavailableError(RuntimeError):
    """Raised when the optional BibLaTeX parser is unavailable."""


@dataclass(frozen=True)
class BibliographyImport:
    records: tuple[ReferenceRecord, ...]
    occurrences: tuple[BibliographyOccurrence, ...]


def load_bibliography(
    path: Path,
    *,
    source_id: str,
    source_revision: str | None = None,
    source_path: str | None = None,
) -> BibliographyImport:
    """Load records while preserving their bibliography occurrence."""
    try:
        from pybtex.database import parse_string  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - environment dependent
        raise BibLaTeXUnavailableError(
            "BibLaTeX import requires the 'bibtex' project extra"
        ) from error

    database: Any = parse_string(
        read_path_text(path, label="bibliography"),
        bib_format="bibtex",
    )
    records: list[ReferenceRecord] = []
    occurrences: list[BibliographyOccurrence] = []
    occurrence_path = source_path or path.name

    for citekey, entry in database.entries.items():
        fields = {
            str(key).lower(): str(value) for key, value in entry.fields.items()
        }
        authors = tuple(
            str(person) for person in entry.persons.get("author", ())
        )
        year = fields.get("year") or fields.get("date")
        records.append(
            ReferenceRecord(
                citekey=citekey,
                entry_type=str(entry.type).lower(),
                title=fields.get("title"),
                authors=authors,
                year=year,
                doi=normalize_doi(fields.get("doi")),
                isbn=fields.get("isbn"),
                url=fields.get("url"),
                eprint=fields.get("eprint"),
            )
        )
        occurrences.append(
            BibliographyOccurrence(
                citekey=citekey,
                source_id=source_id,
                source_revision=source_revision,
                source_path=occurrence_path,
            )
        )

    return BibliographyImport(tuple(records), tuple(occurrences))
