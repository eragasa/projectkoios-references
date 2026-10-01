from enum import StrEnum


class CitationKeyResolutionStatus(StrEnum):
    """Literal-key correlation without first-match selection."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
