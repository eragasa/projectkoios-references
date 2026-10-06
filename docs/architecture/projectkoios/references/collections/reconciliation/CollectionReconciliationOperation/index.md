# `CollectionReconciliationOperation`

Runtime-neutral owner actionizer for the complete collection-reconciliation and
create-once publication lifecycle. Its stable action identity is
`projectkoios.references.collections.reconciliation.operation@1` so an external
runtime can bind the exact owner action without inferring topology from source
or domain records.

The action consumes one exact
[`CollectionReconciliationOperationRequest`](../CollectionReconciliationOperationRequest/index.md),
invokes only References-owned readers, reducers, and publisher actions, and
returns one
[`CollectionReconciliationOperationResult`](../CollectionReconciliationOperationResult/index.md).
It introduces no scheduler, retry, checkpoint, approval, CPN marking, or
Workflow dependency.

The command adapter imports this class directly from `operation.py`; the package
initializer and root facade remain unchanged.

Evidence: [implementation](../implementation.md).
