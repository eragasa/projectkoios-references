"""Reference/document linkage provenance."""

from enum import StrEnum


class ReferenceDocumentLinkageBasis(StrEnum):
    """Identify why a neutral document/reference binding exists."""

    EXPLICIT_SELECTION = "explicit-reference-document-selection"
    VERIFIED_LOCAL_EVIDENCE_IMPORT = "verified-local-evidence-import"
