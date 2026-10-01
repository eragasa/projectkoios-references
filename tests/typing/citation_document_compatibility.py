"""Static compatibility assertions for the deprecated document facade."""

from projectkoios.references.bibliography import (
    CitationBibliographyObservationBinding as CanonicalBinding,
)
from projectkoios.references.citation_document import (
    CitationBibliographyObservationBinding,
    CitationDocumentProjector,
    CitationTargetSnapshot,
)
from projectkoios.references.citations import (
    CitationTargetSnapshot as CanonicalSnapshot,
)
from projectkoios.references.documents import (
    CitationDocumentProjector as CanonicalProjector,
)

projector_type: type[CanonicalProjector] = CitationDocumentProjector
snapshot_type: type[CanonicalSnapshot] = CitationTargetSnapshot
binding_type: type[CanonicalBinding] = CitationBibliographyObservationBinding
