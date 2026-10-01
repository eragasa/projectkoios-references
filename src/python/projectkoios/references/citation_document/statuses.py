from enum import StrEnum


class CitationKeyResolutionStatus(StrEnum):
    """Literal-key correlation without first-match selection."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class CitationBibliographyMembershipStatus(StrEnum):
    """Target bibliography membership, separate from identity resolution."""

    DEFINED = "defined"
    UNDEFINED = "undefined"
    NOT_EVALUATED = "not-evaluated"


class CitationDocumentAvailabilityStatus(StrEnum):
    """Document evidence separate from rights, use, and ingestion."""

    NOT_EVALUATED = "not-evaluated"
    NOT_OBSERVED = "not-observed"
    AVAILABLE_UNVERIFIED_LINKAGE = "available-unverified-linkage"
    AVAILABLE_LINKED = "available-linked"
    AMBIGUOUS = "ambiguous"
    INACCESSIBLE = "inaccessible"
