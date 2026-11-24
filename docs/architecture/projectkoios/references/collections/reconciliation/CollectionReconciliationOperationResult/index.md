# `CollectionReconciliationOperationResult`

Immutable result binding the exact operation request to both the owner
[`CollectionReconciliationResult`](../CollectionReconciliationResult/index.md)
and the exact
[`ReconciliationPublicationResult`](../ReconciliationPublicationResult/index.md).

Construction requires the publication to consume the reconciliation's exact
outputs and the request's exact destination capability. This exposes the
owner-defined reduction and publication lifecycle without persisting generic
workflow state or weakening create-once verification. Publication status
remains `created` or `unchanged`; incomplete or conflicting destinations fail
instead of being repaired.

Evidence: [implementation](../implementation.md).
