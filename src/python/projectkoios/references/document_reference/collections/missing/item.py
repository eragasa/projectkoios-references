"""Missing-PDF display row."""

from dataclasses import dataclass

from ...bibliography.metadata.display import (
    ReferenceDisplayMetadata,
)
from ..pdf_requirement import (
    PdfRequirement,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MissingPdfReference(ReferenceDisplayMetadata):
    """Describe one privacy-reduced missing-PDF row."""

    pdf_requirement: PdfRequirement = PdfRequirement.REQUIRED

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.pdf_requirement is not PdfRequirement.REQUIRED:
            raise ValueError(
                "a missing PDF row must have requirement 'required'"
            )
