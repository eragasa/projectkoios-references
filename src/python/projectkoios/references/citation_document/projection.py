"""Deprecated exact-object exports from the canonical documents package."""

import warnings

from projectkoios.references.documents.projection import (
    CitationDocumentProjection,
    CitationDocumentProjectionItem,
    CitationDocumentProjectionRequest,
    CitationDocumentProjectionResult,
    CitationDocumentProjector,
    projection_for,
)

warnings.warn(
    "projectkoios.references.citation_document.projection is deprecated; "
    "import from projectkoios.references.documents.projection instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CitationDocumentProjection",
    "CitationDocumentProjectionItem",
    "CitationDocumentProjectionRequest",
    "CitationDocumentProjectionResult",
    "CitationDocumentProjector",
    "projection_for",
]
