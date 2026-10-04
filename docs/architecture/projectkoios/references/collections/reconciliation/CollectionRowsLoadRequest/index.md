# `CollectionRowsLoadRequest`

Immutable bounded request for loading canonical collection rows from an authorized root-relative source.

It is owned by `loading.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
