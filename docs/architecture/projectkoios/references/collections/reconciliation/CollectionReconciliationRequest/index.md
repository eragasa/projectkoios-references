# `CollectionReconciliationRequest`

Immutable request binding all collection, bibliography, citation, review, acquisition, and processing evidence used by reconciliation.

It is owned by `reconciliation.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
