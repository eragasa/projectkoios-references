# `CollectionRowsLoader`

Actionizer that validates one exact request and loads bounded collection rows through the canonical parser.

It is owned by `loading.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
