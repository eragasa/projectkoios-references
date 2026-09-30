# `CitationIdentityProjectionRequest`

Frozen, slotted, keyword-only `DataObjectActionRequest` containing:

- one replay-derived `IdentityProjection`;
- a nonempty canonical tuple of unique opaque bibliographic identity IDs; and
- a derived `request_id` binding that tuple to the input `projection_id`.

The tuple is lexically sorted and limited to 1,024 items. Each ID is nonempty,
unpadded, control-free UTF-8 no longer than 512 bytes. IDs remain opaque: the
request does not infer authority from a prefix or turn a candidate ID into an
accepted-reference ID.

Evidence: [module implementation](../implementation.md) and
[`test__CitationIdentityProjection.py`](../../../../../../tests/test__CitationIdentityProjection.py).
