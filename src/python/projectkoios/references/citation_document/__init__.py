"""Canonical citation-document control API with deprecated moved exports."""

from __future__ import annotations

import warnings
from importlib import import_module
from typing import TYPE_CHECKING

from ._contract import (
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
)
from .document import (
    CitationSourceDocumentDescriptor,
    CitationSourceDocumentObservation,
)
from .linkage import (
    CitationSourceDocumentLink,
    CitationSourceDocumentLinker,
    CitationSourceDocumentLinkRequest,
    CitationSourceDocumentLinkResult,
)
from .projection import (
    CitationDocumentProjection,
    CitationDocumentProjectionItem,
    CitationDocumentProjectionRequest,
    CitationDocumentProjectionResult,
    CitationDocumentProjector,
)
from .statuses import CitationDocumentAvailabilityStatus

if TYPE_CHECKING:
    from projectkoios.references.bibliography import (
        CitationBibliographyMembershipStatus,
        CitationBibliographyObservationBinding,
    )
    from projectkoios.references.citations import (
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
_DEPRECATED_EXPORTS = {
    **{
        name: "projectkoios.references.citations"
        for name in _CITATION_DEPRECATED_EXPORTS
    },
    **{
        name: "projectkoios.references.bibliography"
        for name in _BIBLIOGRAPHY_DEPRECATED_EXPORTS
    },
}
_WARNED_DEPRECATED_EXPORTS: set[str] = set()


def __getattr__(name: str) -> object:
    module_name = _DEPRECATED_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name not in _WARNED_DEPRECATED_EXPORTS:
        warnings.warn(
            f"projectkoios.references.citation_document.{name} is deprecated; "
            f"import {name} from {module_name} instead",
            DeprecationWarning,
            stacklevel=2,
        )
        _WARNED_DEPRECATED_EXPORTS.add(name)
    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_DEPRECATED_EXPORTS})


__all__ = [
    "CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS",
    "CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES",
    "CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES",
    "CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS",
    "CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY",
    "CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY",
    "CITATION_DOCUMENT_MAX_ID_BYTES",
    "CITATION_DOCUMENT_MAX_KEYS",
    "CITATION_DOCUMENT_MAX_LINKS",
    "CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY",
    "CITATION_DOCUMENT_MAX_OCCURRENCES",
    "CITATION_DOCUMENT_MAX_PDF_BYTES",
    "CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS",
    "CITATION_DOCUMENT_MAX_SOURCE_GAPS",
    "CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_RECORDS",
    "CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD",
    "CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES",
    "CITATION_DOCUMENT_MAX_TEXT_BYTES",
    "CITATION_DOCUMENT_PROJECTION_CONTRACT_ID",
    "CITATION_DOCUMENT_PROJECTOR_NAME",
    "CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID",
    "CITATION_SOURCE_DOCUMENT_LINKER_NAME",
    "CitationBibliographyMembershipStatus",
    "CitationBibliographyObservationBinding",
    "CitationContentIdentity",
    "CitationDocumentAvailabilityStatus",
    "CitationDocumentProjection",
    "CitationDocumentProjectionItem",
    "CitationDocumentProjectionRequest",
    "CitationDocumentProjectionResult",
    "CitationDocumentProjector",
    "CitationKeyResolutionStatus",
    "CitationSourceDocumentDescriptor",
    "CitationSourceDocumentLink",
    "CitationSourceDocumentLinkRequest",
    "CitationSourceDocumentLinkResult",
    "CitationSourceDocumentLinker",
    "CitationSourceDocumentObservation",
    "CitationSourceLocator",
    "CitationTargetBibliographyEntry",
    "CitationTargetGroup",
    "CitationTargetOccurrence",
    "CitationTargetSnapshot",
    "CitationTargetSourceGap",
]
