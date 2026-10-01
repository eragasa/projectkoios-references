# `projectkoios.references.collection_reconciliation`

This package reconciles bounded collection-row, managed-PDF, coverage,
processing, review, citation-closure, and state-projection evidence into a
deterministic collection manifest and replay-verifiable publication package.
The public import path is unchanged by the package decomposition.

## Public classes

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
- source: [`collection_reconciliation`](../../../../../src/python/projectkoios/references/collection_reconciliation/)
- reconciliation tests: [`test__CollectionReconciliation.py`](../../../../../tests/test__CollectionReconciliation.py)
- publication-package tests: [`test__ReconciliationPackage.py`](../../../../../tests/test__ReconciliationPackage.py)
- [Package index](../index.md)
