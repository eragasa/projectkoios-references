"""Vendor-neutral reference display metadata."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ...base import (
    AbstractDocumentReferenceDataObject,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDisplayMetadata(
    AbstractDocumentReferenceDataObject, DataObjectModel
):
    """Hold privacy-reduced bibliography display fields."""

    citekey: str
    entry_type: str
    title: str | None
    authors: tuple[str, ...]
    year: str | None

    def __post_init__(self) -> None:
        self._validate_identifier(self.citekey, field="citekey")
        self._validate_entry_type(self.entry_type)
        if self.title is not None and (
            type(self.title) is not str
            or not 1 <= len(self.title) <= 2_000
            or not self.title.isprintable()
        ):
            raise ValueError("title must be 1-2000 printable characters")
        if (
            type(self.authors) is not tuple
            or len(self.authors) > 100
            or any(
                type(author) is not str
                or not 1 <= len(author) <= 500
                or not author.isprintable()
                for author in self.authors
            )
        ):
            raise ValueError(
                "authors must contain at most 100 bounded printable names"
            )
        if self.year is not None and (
            type(self.year) is not str
            or not 1 <= len(self.year) <= 64
            or not self.year.isprintable()
        ):
            raise ValueError("year must be 1-64 printable characters")
