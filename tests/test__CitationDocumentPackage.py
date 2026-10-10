"""Package-boundary tests for canonical citation-document control."""

from __future__ import annotations

import warnings

import projectkoios.references.bibliography as bibliography
import projectkoios.references.citation_document as citation_document
import projectkoios.references.citations as citations
import pytest

_CANONICAL_EXPORTS = (
    "CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS",
    "CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY",
    "CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY",
    "CITATION_DOCUMENT_MAX_LINKS",
    "CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY",
    "CITATION_DOCUMENT_MAX_PDF_BYTES",
    "CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS",
    "CITATION_DOCUMENT_PROJECTION_CONTRACT_ID",
    "CITATION_DOCUMENT_PROJECTOR_NAME",
    "CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID",
    "CITATION_SOURCE_DOCUMENT_LINKER_NAME",
    "CitationDocumentAvailabilityStatus",
    "CitationDocumentProjection",
    "CitationDocumentProjectionItem",
    "CitationDocumentProjectionRequest",
    "CitationDocumentProjectionResult",
    "CitationDocumentProjector",
    "CitationSourceDocumentDescriptor",
    "CitationSourceDocumentLink",
    "CitationSourceDocumentLinkRequest",
    "CitationSourceDocumentLinkResult",
    "CitationSourceDocumentLinker",
    "CitationSourceDocumentObservation",
)
_MOVED_EXPORTS = (
    "CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES",
    "CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES",
    "CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS",
    "CITATION_DOCUMENT_MAX_ID_BYTES",
    "CITATION_DOCUMENT_MAX_KEYS",
    "CITATION_DOCUMENT_MAX_OCCURRENCES",
    "CITATION_DOCUMENT_MAX_SOURCE_GAPS",
    "CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_RECORDS",
    "CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD",
    "CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES",
    "CITATION_DOCUMENT_MAX_TEXT_BYTES",
    "CitationBibliographyMembershipStatus",
    "CitationBibliographyObservationBinding",
    "CitationContentIdentity",
    "CitationKeyResolutionStatus",
    "CitationSourceLocator",
    "CitationTargetBibliographyEntry",
    "CitationTargetGroup",
    "CitationTargetOccurrence",
    "CitationTargetSnapshot",
    "CitationTargetSourceGap",
)


def test__citation_document_package__exports_only_owned_contracts() -> None:
    """Keep the package facade exact and free of moved compatibility names."""

    assert tuple(citation_document.__all__) == _CANONICAL_EXPORTS
    for name in _CANONICAL_EXPORTS:
        value = getattr(citation_document, name)
        assert name.isupper() or value.__module__.startswith(
            "projectkoios.references.citation_document"
        )

    for name in _MOVED_EXPORTS:
        assert name not in citation_document.__all__
        assert name not in dir(citation_document)
        with pytest.raises(AttributeError):
            getattr(citation_document, name)


def test__canonical_imports__are_warning_free() -> None:
    """Require consumers to import moved records from their sole owners."""

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        assert citations.CitationTargetSnapshot.__module__ == (
            "projectkoios.references.citations.base"
        )
        assert (
            bibliography.CitationBibliographyObservationBinding.__module__
            == "projectkoios.references.bibliography.base"
        )

    assert captured == []
