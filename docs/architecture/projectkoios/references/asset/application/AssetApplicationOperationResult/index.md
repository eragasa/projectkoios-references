# `AssetApplicationOperationResult`

Immutable typed result binding the exact request to the canonical parsed plan,
actor-provenanced authorization, replayed identity projection, selected
candidate, exact schema-5 source-asset record, and materialization effect.

`materialization.created` distinguishes new publication from an identical
existing file. `catalog_record_present` means the exact record is present after
a successful transaction; it is false only when no catalog capability was
requested. Effect disposition may differ on replay while semantic evidence and
bytes remain equal.

Evidence: [implementation](../implementation.md).
