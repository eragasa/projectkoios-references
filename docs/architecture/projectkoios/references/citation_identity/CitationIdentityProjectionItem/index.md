# `CitationIdentityProjectionItem`

Frozen, slotted, keyword-only `DataObjectModel` for exactly one requested
identity. `requested_identity_id` preserves correlation and `projection_id`
identifies the replay state used to classify it.

Field combinations are status-closed:

- active accepted items carry `reference_id` and `canonical_citekey` only;
- candidate items carry `proposed_citekey` but no accepted `reference_id` or
  canonical key;
- superseded items carry their reference ID and canonical successor IDs;
- accepted-without-name and unresolved items carry no citekey.

`item_id` binds all fields with a canonical in-memory digest. It is not a
persistence or interchange schema.

Evidence: [module implementation](../implementation.md) and
[`test__CitationIdentityProjection.py`](../../../../../../tests/test__CitationIdentityProjection.py).
