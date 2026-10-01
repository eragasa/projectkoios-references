"""Deprecated exact-object exports from the canonical documents package."""

import warnings

from projectkoios.references.documents.statuses import (
    CitationDocumentAvailabilityStatus,
)

warnings.warn(
    "projectkoios.references.citation_document.statuses is deprecated; "
    "import from projectkoios.references.documents.statuses instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["CitationDocumentAvailabilityStatus"]
