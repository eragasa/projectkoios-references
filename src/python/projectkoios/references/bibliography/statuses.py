from enum import StrEnum


class CitationBibliographyMembershipStatus(StrEnum):
    """Target bibliography membership, separate from identity resolution."""

    DEFINED = "defined"
    UNDEFINED = "undefined"
    NOT_EVALUATED = "not-evaluated"
