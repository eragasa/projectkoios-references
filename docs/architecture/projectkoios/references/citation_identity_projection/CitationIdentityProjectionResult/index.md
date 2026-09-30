# `CitationIdentityProjectionResult`

Frozen, slotted, keyword-only `DataObjectActionResult` binding one exact request
to an ordered tuple of `CitationIdentityProjectionItem` objects.

Construction requires item IDs to appear in the same order as the request's
identity IDs and requires every item to carry the request projection's
`projection_id`. Duplicate item identities fail closed. The derived `result_id`
binds request ID, projection ID, and ordered item IDs.

The result is a deterministic in-memory action result, not a serialization
contract, database record, target-bibliography assertion, or citation decision.

Evidence: [module implementation](../implementation.md) and
[`test__CitationIdentityProjection.py`](../../../../../../tests/test__CitationIdentityProjection.py).
