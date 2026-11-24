"""Bibliography metadata reader port."""

from typing import Protocol

from .display import (
    ReferenceDisplayMetadata,
)


class BibliographyMetadataReader(Protocol):
    """Read one exact entry through a vendor-neutral boundary."""

    def read(
        self, *, citekey: str, bibtex_entry: str
    ) -> ReferenceDisplayMetadata: ...
