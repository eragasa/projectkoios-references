# `ReconciliationPackageParseRequest`

Immutable bounded request for parsing a reconciliation package from an authorized directory.

It is owned by `publication.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
