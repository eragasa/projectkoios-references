"""Deprecated exact-object exports from the canonical documents package."""

import warnings

from projectkoios.references.documents.linkage import (
    CitationSourceDocumentLink,
    CitationSourceDocumentLinker,
    CitationSourceDocumentLinkRequest,
    CitationSourceDocumentLinkResult,
    link_for,
)

warnings.warn(
    "projectkoios.references.citation_document.linkage is deprecated; "
    "import from projectkoios.references.documents.linkage instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CitationSourceDocumentLink",
    "CitationSourceDocumentLinkRequest",
    "CitationSourceDocumentLinkResult",
    "CitationSourceDocumentLinker",
    "link_for",
]
