# `CollectionReconciler`

Actionizer that validates one exact request and executes the sole canonical reconciliation path.

It is owned by `reconciliation.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
