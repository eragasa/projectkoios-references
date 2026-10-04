# `ReconciliationPackageParser`

Actionizer that parses canonical package bytes without granting publication or content-use authority.

It is owned by `publication.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
