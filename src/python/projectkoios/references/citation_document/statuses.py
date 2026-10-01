from enum import StrEnum


class CitationDocumentAvailabilityStatus(StrEnum):
    """Document evidence separate from rights, use, and ingestion."""

    NOT_EVALUATED = "not-evaluated"
    NOT_OBSERVED = "not-observed"
    AVAILABLE_UNVERIFIED_LINKAGE = "available-unverified-linkage"
    AVAILABLE_LINKED = "available-linked"
    AMBIGUOUS = "ambiguous"
    INACCESSIBLE = "inaccessible"
