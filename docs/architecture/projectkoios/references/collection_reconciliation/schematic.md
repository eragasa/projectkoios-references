# Collection reconciliation schematic

```mermaid
classDiagram
    class CollectionReconciliationError
    class IncompleteReconciliationPublicationError
    class EvidenceMapping
    class PdfExpectation
    class PdfStatus
    class CitationStatus
    class CollectionRowEvidence
    class ProcessingEvidence
    class ManagedPdf
    class ManagedPdfScan
    class CollectionReference
    class ExtraPdf
    class CollectionManifest
    class ReconciliationOutputs
    class PublicationResult
    CollectionReconciliationError <|-- IncompleteReconciliationPublicationError
    EvidenceMapping o-- CollectionRowEvidence
    ManagedPdfScan o-- ManagedPdf
    CollectionReference --> PdfExpectation
    CollectionReference --> PdfStatus
    CollectionReference --> CitationStatus
    CollectionManifest o-- CollectionReference
    CollectionManifest o-- ExtraPdf
    ReconciliationOutputs --> CollectionManifest
```

Public functions load bounded evidence, reconcile it once, render deterministic
outputs, and publish only an exactly verified package. Private modules add no
parallel contracts or alternate publication path.

- [Module index](index.md)
- [Implementation](implementation.md)
