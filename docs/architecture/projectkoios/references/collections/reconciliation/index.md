# `projectkoios.references.collections.reconciliation`

This package reconciles bounded collection-row, managed-PDF, coverage,
processing, review, citation-closure, and state-projection evidence into a
deterministic collection manifest and replay-verifiable publication package.
It is the sole canonical collection-reconciliation namespace; no compatibility
facade exists at `projectkoios.references.collection_reconciliation`.

## Action families

Loading and scanning:

- [`CollectionRowsLoadRequest`](CollectionRowsLoadRequest/index.md)
- [`CollectionRowsLoadResult`](CollectionRowsLoadResult/index.md)
- [`CollectionRowsLoader`](CollectionRowsLoader/index.md)
- [`ManagedPdfScanRequest`](ManagedPdfScanRequest/index.md)
- [`ManagedPdfScanResult`](ManagedPdfScanResult/index.md)
- [`ManagedPdfScanner`](ManagedPdfScanner/index.md)

Reconciliation:

- [`CollectionReconciliationRequest`](CollectionReconciliationRequest/index.md)
- [`CollectionReconciliationResult`](CollectionReconciliationResult/index.md)
- [`CollectionReconciler`](CollectionReconciler/index.md)

Publication, parsing, verification, and replay:

- [`ReconciliationPublicationRequest`](ReconciliationPublicationRequest/index.md)
- [`ReconciliationPublicationResult`](ReconciliationPublicationResult/index.md)
- [`ReconciliationPublisher`](ReconciliationPublisher/index.md)
- [`ReconciliationPackageParseRequest`](ReconciliationPackageParseRequest/index.md)
- [`ReconciliationPackageParseResult`](ReconciliationPackageParseResult/index.md)
- [`ReconciliationPackageParser`](ReconciliationPackageParser/index.md)
- [`ReconciliationPackageVerificationRequest`](ReconciliationPackageVerificationRequest/index.md)
- [`ReconciliationPackageVerificationResult`](ReconciliationPackageVerificationResult/index.md)
- [`ReconciliationPackageVerifier`](ReconciliationPackageVerifier/index.md)
- [`ReconciliationReplayRequest`](ReconciliationReplayRequest/index.md)
- [`ReconciliationReplayResult`](ReconciliationReplayResult/index.md)
- [`ReconciliationReplayer`](ReconciliationReplayer/index.md)

## Data objects and statuses

- [`CollectionReconciliationError`](CollectionReconciliationError/index.md)
- [`IncompleteReconciliationPublicationError`](IncompleteReconciliationPublicationError/index.md)
- [`EvidenceMapping`](EvidenceMapping/index.md)
- [`PdfExpectation`](PdfExpectation/index.md)
- [`PdfStatus`](PdfStatus/index.md)
- [`CitationStatus`](CitationStatus/index.md)
- [`CollectionRowEvidence`](CollectionRowEvidence/index.md)
- [`ProcessingEvidence`](ProcessingEvidence/index.md)
- [`ManagedPdf`](ManagedPdf/index.md)
- [`ManagedPdfScan`](ManagedPdfScan/index.md)
- [`CollectionReference`](CollectionReference/index.md)
- [`ExtraPdf`](ExtraPdf/index.md)
- [`CollectionManifest`](CollectionManifest/index.md)
- [`ReconciliationOutputs`](ReconciliationOutputs/index.md)
- [`PublicationResult`](PublicationResult/index.md)

## Authority boundary

Reconciliation preserves and projects supplied evidence. It does not create
identity, rights, reading, scientific, Search, ingestion, use, or publication
authority. Publication succeeds only after package files and the manifest replay
exactly and the completed output directory verifies in place.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [Canonical source package](../../../../../../src/python/projectkoios/references/collections/reconciliation/)
- [Mirrored tests](../../../../../../tests/package/projectkoios/references/collections/reconciliation/)
- [References package index](../../index.md)
