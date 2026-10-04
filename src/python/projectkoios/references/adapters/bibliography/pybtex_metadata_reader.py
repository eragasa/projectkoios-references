"""PyBTeX adapter for vendor-neutral bibliography display metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, cast, final

from projectkoios.references.document_reference import (
    BibliographyMetadataError,
    ReferenceDisplayMetadata,
)
from pybtex.database import parse_string  # type: ignore[import-untyped]
from pybtex.scanner import PybtexSyntaxError  # type: ignore[import-untyped]


class _PybtexPerson(Protocol):
    def __str__(self) -> str: ...


class _PybtexEntry(Protocol):
    type: str
    fields: Mapping[str, str]
    persons: Mapping[str, Sequence[_PybtexPerson]]


@final
class PybtexBibliographyMetadataReader:
    """Parse one BibTeX entry without exposing PyBTeX-owned values."""

    def read(
        self,
        *,
        citekey: str,
        bibtex_entry: str,
    ) -> ReferenceDisplayMetadata:
        try:
            bibliography = parse_string(bibtex_entry, "bibtex")
            entries = cast(
                Mapping[str, _PybtexEntry],
                bibliography.entries,
            )
        except (PybtexSyntaxError, UnicodeError, ValueError) as error:
            raise BibliographyMetadataError(
                "bibtex_entry is not valid BibTeX"
            ) from error
        if tuple(entries) != (citekey,):
            raise BibliographyMetadataError(
                "bibtex_entry must contain exactly the declared citekey"
            )
        entry = entries[citekey]
        title = self._display_text(entry.fields.get("title"))
        year = self._display_text(
            entry.fields.get("year") or entry.fields.get("date")
        )
        authors: list[str] = []
        for person in entry.persons.get("author", ()):
            author = self._display_text(str(person))
            if author is not None:
                authors.append(author)
        try:
            return ReferenceDisplayMetadata(
                citekey=citekey,
                entry_type=entry.type.lower(),
                title=title,
                authors=tuple(authors),
                year=year,
            )
        except ValueError as error:
            raise BibliographyMetadataError(
                "bibtex_entry display metadata exceeds supported bounds"
            ) from error

    @staticmethod
    def _display_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None
