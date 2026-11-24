# `AssetApplicationOperation`

Final runtime-neutral actionizer for the complete authorized asset-application
lifecycle. It exposes stable action identity
`projectkoios.references.asset.application@1` and accepts only the
exact [`AssetApplicationOperationRequest`](../AssetApplicationOperationRequest/index.md)
type.

When catalog recording is requested, the action preserves the existing
indivisible lock/preflight/publication/insert protocol. It returns only after a
successful catalog commit, or raises the original failure while retaining an
already-published exact file for explicit replay reconciliation.

Evidence: [implementation](../implementation.md).
