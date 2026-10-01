# Citation document control schematic

```mermaid
classDiagram
    class DataObjectActionRequest
    class DataObjectActionResult
    class DataObjectActionizer
    class CitationTargetSnapshot
    class IdentityProjection
    class CitationDocumentProjectionRequest
    class CitationDocumentProjection
    class CitationDocumentProjectionItem
    class CitationDocumentProjectionResult
    class CitationDocumentProjector
    class CitationSourceDocumentLinkRequest
    class CitationSourceDocumentLink
    class CitationSourceDocumentLinkResult
    class CitationSourceDocumentLinker

    DataObjectActionRequest <|-- CitationDocumentProjectionRequest
    CitationDocumentProjectionRequest --> CitationTargetSnapshot
    CitationDocumentProjectionRequest --> IdentityProjection
    CitationDocumentProjector --> CitationDocumentProjectionResult
    DataObjectActionizer <|-- CitationDocumentProjector
    DataObjectActionResult <|-- CitationDocumentProjectionResult
    CitationDocumentProjectionResult --> CitationDocumentProjection
    CitationDocumentProjection o-- CitationDocumentProjectionItem

    DataObjectActionRequest <|-- CitationSourceDocumentLinkRequest
    CitationSourceDocumentLinkRequest --> CitationDocumentProjectionResult
    CitationSourceDocumentLinker --> CitationSourceDocumentLinkResult
    DataObjectActionizer <|-- CitationSourceDocumentLinker
    DataObjectActionResult <|-- CitationSourceDocumentLinkResult
    CitationSourceDocumentLinkResult --> CitationSourceDocumentLink
```

The target snapshot and identity replay enter from their owners. The projection
is rebuilt after a neutral link is created; no mutable attachment row or
last-write-wins state exists.

- [Module index](index.md)
- [Implementation](implementation.md)
