"""Canonical citation-document projection and linkage API."""

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

__all__ = [
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
]
