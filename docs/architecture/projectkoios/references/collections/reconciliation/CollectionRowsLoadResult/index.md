# `CollectionRowsLoadResult`

Immutable result containing the exact validated collection-row evidence sequence.

It is owned by `loading.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
