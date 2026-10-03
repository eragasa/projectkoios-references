# `ReferenceStateReplayer`

Stateless `DataObjectActionizer` for deterministic reference-state reduction.
`action(*, request)` delegates to `replay(*, request)`, which validates
cross-object relationships, groups claims without source preference, preserves
discrepancies, constructs complete field coverage, and returns a request-bound
result.

All supporting behavior is owned by private methods on the replayer. It has no
filesystem, database, network, workflow, or publication effects.

Evidence: [module implementation](../implementation.md) and
[`test__StateProjection.py`](../../../../../../tests/test__StateProjection.py).
