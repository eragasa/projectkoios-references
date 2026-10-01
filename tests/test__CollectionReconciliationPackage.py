from __future__ import annotations

from typing import get_type_hints

from projectkoios.references import (
    CollectionManifest as RootCollectionManifest,
)
from projectkoios.references import (
    reconcile_collection as root_reconcile_collection,
)
from projectkoios.references.citation_closure import (
    build_citation_closure as canonical_build_citation_closure,
)
from projectkoios.references.collection_reconciliation import (
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
    build_citation_closure,
    load_collection_rows,
    loading,
    models,
    parse_reconciliation_package,
    publication,
    publish_reconciliation,
    reconcile_collection,
    reconciliation,
    replay_reconciliation,
    scan_managed_pdfs,
    verify_reconciliation_package,
)

_MODEL_TYPES = (
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


def test__collection_reconciliation_package__preserves_public_identities() -> (
    None
):
    assert RootCollectionManifest is CollectionManifest
    assert root_reconcile_collection is reconcile_collection
    assert build_citation_closure is canonical_build_citation_closure

    assert all(
        value is getattr(models, value.__name__) for value in _MODEL_TYPES
    )
    assert load_collection_rows is loading.load_collection_rows
    assert scan_managed_pdfs is loading.scan_managed_pdfs
    assert reconcile_collection is reconciliation.reconcile_collection
    assert publish_reconciliation is publication.publish_reconciliation
    assert (
        parse_reconciliation_package is publication.parse_reconciliation_package
    )
    assert (
        verify_reconciliation_package
        is publication.verify_reconciliation_package
    )
    assert replay_reconciliation is publication.replay_reconciliation


def test__collection_reconciliation_package__resolves_public_annotations() -> (
    None
):
    for value in _MODEL_TYPES:
        get_type_hints(value)
    for value in (
        load_collection_rows,
        parse_reconciliation_package,
        publish_reconciliation,
        reconcile_collection,
        replay_reconciliation,
        scan_managed_pdfs,
        verify_reconciliation_package,
    ):
        get_type_hints(value)
