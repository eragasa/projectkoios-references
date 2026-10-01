"""Deprecated compatibility facade for the canonical documents package."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from projectkoios.references import bibliography as _bibliography
from projectkoios.references import citations as _citations
from projectkoios.references import documents as _documents

if TYPE_CHECKING:
    from projectkoios.references.bibliography import (  # noqa: F401
        CitationBibliographyMembershipStatus,
        CitationBibliographyObservationBinding,
    )
    from projectkoios.references.citations import (  # noqa: F401
        CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES,
        CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES,
        CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS,
        CITATION_DOCUMENT_MAX_ID_BYTES,
        CITATION_DOCUMENT_MAX_KEYS,
        CITATION_DOCUMENT_MAX_OCCURRENCES,
        CITATION_DOCUMENT_MAX_SOURCE_GAPS,
        CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES,
        CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES,
        CITATION_DOCUMENT_MAX_TARGET_RECORDS,
        CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD,
        CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES,
        CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES,
        CITATION_DOCUMENT_MAX_TEXT_BYTES,
        CitationContentIdentity,
        CitationKeyResolutionStatus,
        CitationSourceLocator,
        CitationTargetBibliographyEntry,
        CitationTargetGroup,
        CitationTargetOccurrence,
        CitationTargetSnapshot,
        CitationTargetSourceGap,
    )
    from projectkoios.references.documents import (  # noqa: F401
        CITATION_DOCUMENT_AVAILABILITY_EVALUATOR_NAME,
        CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS,
        CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
        CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY,
        CITATION_DOCUMENT_MAX_LINKS,
        CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY,
        CITATION_DOCUMENT_MAX_PDF_BYTES,
        CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS,
        CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
        CITATION_DOCUMENT_PROJECTOR_NAME,
        CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
        CITATION_SOURCE_DOCUMENT_LINKER_NAME,
        CitationDocumentAvailabilityEvaluationRequest,
        CitationDocumentAvailabilityEvaluationResult,
        CitationDocumentAvailabilityEvaluator,
        CitationDocumentAvailabilityStatus,
        CitationDocumentProjection,
        CitationDocumentProjectionItem,
        CitationDocumentProjectionRequest,
        CitationDocumentProjectionResult,
        CitationDocumentProjector,
        CitationSourceDocumentDescriptor,
        CitationSourceDocumentLink,
        CitationSourceDocumentLinker,
        CitationSourceDocumentLinkRequest,
        CitationSourceDocumentLinkResult,
        CitationSourceDocumentObservation,
    )

_CITATION_DEPRECATED_EXPORTS = frozenset(
    {
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
        "CitationContentIdentity",
        "CitationKeyResolutionStatus",
        "CitationSourceLocator",
        "CitationTargetBibliographyEntry",
        "CitationTargetGroup",
        "CitationTargetOccurrence",
        "CitationTargetSnapshot",
        "CitationTargetSourceGap",
    }
)
_BIBLIOGRAPHY_DEPRECATED_EXPORTS = frozenset(
    {
        "CitationBibliographyMembershipStatus",
        "CitationBibliographyObservationBinding",
    }
)
_WARNED_DEPRECATED_EXPORTS: set[str] = set()


def __getattr__(name: str) -> object:
    if name in _CITATION_DEPRECATED_EXPORTS:
        value = getattr(_citations, name)
        owner = "projectkoios.references.citations"
    elif name in _BIBLIOGRAPHY_DEPRECATED_EXPORTS:
        value = getattr(_bibliography, name)
        owner = "projectkoios.references.bibliography"
    elif name in _documents.__all__:
        value = getattr(_documents, name)
        owner = "projectkoios.references.documents"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name not in _WARNED_DEPRECATED_EXPORTS:
        warnings.warn(
            f"projectkoios.references.citation_document.{name} is deprecated; "
            f"import {name} from {owner} instead",
            DeprecationWarning,
            stacklevel=2,
        )
        _WARNED_DEPRECATED_EXPORTS.add(name)
    return value


def __dir__() -> list[str]:
    return sorted(
        {
            *globals(),
            *_documents.__all__,
            *_CITATION_DEPRECATED_EXPORTS,
            *_BIBLIOGRAPHY_DEPRECATED_EXPORTS,
        }
    )


__all__ = [
    *_documents.__all__,
    *sorted(_CITATION_DEPRECATED_EXPORTS),
    *sorted(_BIBLIOGRAPHY_DEPRECATED_EXPORTS),
]
