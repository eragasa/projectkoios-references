from __future__ import annotations

from projectkoios.references.citation_closure import build_citation_closure

from .loading import load_collection_rows, scan_managed_pdfs
from .models import (
    CitationStatus,
    CollectionManifest,
    CollectionReconciliationError,
    CollectionReference,
    CollectionRowEvidence,
    EvidenceMapping,
    ExtraPdf,
    IncompleteReconciliationPublicationError,
    ManagedPdf,
    ManagedPdfScan,
    PdfExpectation,
    PdfStatus,
    ProcessingEvidence,
    PublicationResult,
    ReconciliationOutputs,
)
from .publication import (
    parse_reconciliation_package,
    publish_reconciliation,
    replay_reconciliation,
    verify_reconciliation_package,
)
from .reconciliation import reconcile_collection

__all__ = [
    "CollectionReconciliationError",
    "IncompleteReconciliationPublicationError",
    "EvidenceMapping",
    "PdfExpectation",
    "PdfStatus",
    "CitationStatus",
    "CollectionRowEvidence",
    "ProcessingEvidence",
    "ManagedPdf",
    "ManagedPdfScan",
    "CollectionReference",
    "ExtraPdf",
    "CollectionManifest",
    "ReconciliationOutputs",
    "PublicationResult",
    "build_citation_closure",
    "load_collection_rows",
    "parse_reconciliation_package",
    "publish_reconciliation",
    "reconcile_collection",
    "replay_reconciliation",
    "scan_managed_pdfs",
    "verify_reconciliation_package",
]
