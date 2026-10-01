# Bibliography schematic

```mermaid
classDiagram
    CitationTargetBibliographyEntry --> CitationBibliographyObservationBinding
    SourceBibliographyObservation --> CitationBibliographyObservationBinding
    CitationBibliographyObservationBinding --> CitationDocumentProjectionRequest
```

Membership status remains orthogonal to accepted reference identity and to
source-document availability.

- [Module index](index.md)
- [Implementation](implementation.md)
- [Package index](../index.md)
