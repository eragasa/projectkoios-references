"""Deprecated exact-object exports from the canonical documents package."""

import warnings

from projectkoios.references.documents.document import (
    CitationSourceDocumentDescriptor,
    CitationSourceDocumentObservation,
)

warnings.warn(
    "projectkoios.references.citation_document.document is deprecated; "
    "import from projectkoios.references.documents.document instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CitationSourceDocumentDescriptor",
    "CitationSourceDocumentObservation",
]
