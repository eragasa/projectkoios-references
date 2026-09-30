# `CitationIdentityProjectionRequest`

Frozen, slotted, keyword-only `DataObjectActionRequest` containing:

- one replay-derived `IdentityProjection`;
- a nonempty canonical tuple of unique opaque bibliographic identity IDs; and
- a derived `request_id` binding that tuple to the input `projection_id`.

Before deriving `request_id`, construction replays the projection's candidates
and decisions with the identity owner and requires exact equality with the
supplied projection. Modified derived content cannot retain an earlier
`projection_id`.

The tuple is lexically sorted and limited to 1,024 items. Validation rejects
more than 512 code points before UTF-8 encoding, then enforces the 512-byte,
trim, and control-character bounds. IDs remain opaque: the request does not
infer authority from a prefix or turn a candidate ID into an accepted-reference
ID.

Evidence: [module implementation](../implementation.md) and
[`test__CitationIdentityProjection.py`](../../../../../../tests/test__CitationIdentityProjection.py).
