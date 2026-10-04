# `ReferenceStateReplayResult`

Immutable, slotted `DataObjectActionResult` binding one exact replay request to
one validated `ReferenceStateProjection`. It rejects subject or declared-input
mismatches and derives `result_id` from the request and projection identities.

The result reports deterministic reduction only. It carries no promotion,
rights, scientific, manuscript, contract, or publication decision.

Evidence: [module implementation](../implementation.md) and
[`test__StateProjection.py`](../../../../../../tests/test__StateProjection.py).
