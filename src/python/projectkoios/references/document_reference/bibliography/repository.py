"""Reference-record persistence port."""

from typing import Protocol

from .record import (
    ReferenceRecord,
)


class ReferenceRecordRepository(Protocol):
    """Persist exact BibTeX reference records."""

    def record_reference(self, *, reference: ReferenceRecord) -> None: ...
