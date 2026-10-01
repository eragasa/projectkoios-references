from __future__ import annotations


class CollectionReconciliationError(RuntimeError):
    """Raised when collection evidence cannot be reconciled safely."""


class IncompleteReconciliationPublicationError(CollectionReconciliationError):
    """A claimed output directory lacks a verified completion state."""

    code = "reconciliation-publication-incomplete"
