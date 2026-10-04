"""One BibTeX reference record."""

from dataclasses import dataclass

from projectkoios.base import DataObjectModel

from ..base import (
    AbstractDocumentReferenceDataObject,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRecord(AbstractDocumentReferenceDataObject, DataObjectModel):
    """Store the complete BibTeX entry for one citekey."""

    citekey: str
    bibtex_entry: str

    def __post_init__(self) -> None:
        self._validate_identifier(self.citekey, field="citekey")
        if (
            type(self.bibtex_entry) is not str
            or not 1 <= len(self.bibtex_entry.encode("utf-8")) <= 262_144
        ):
            raise ValueError("bibtex_entry must contain 1-262144 UTF-8 bytes")
