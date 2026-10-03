# `ReferenceStateReplayRequest`

Immutable, slotted `DataObjectActionRequest` for one deterministic state replay.
It carries the subject identity, typed state claims, complete declared input
identities, and explicit exclusions. Construction enforces type and record
bounds and derives `request_id` from canonical represented intent.

`from_iterables` is the bounded compatibility constructor for callers that do
not already hold tuples.

Evidence: [module implementation](../implementation.md) and
[`test__StateProjection.py`](../../../../../../tests/test__StateProjection.py).
