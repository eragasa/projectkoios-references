# `CatalogSchemaInfo`

Frozen report of the exact current schema version, normalized SQL fingerprint,
and the non-authoritative rebuildable-working-projection boundary. Construction
of this report follows full schema and persisted-row validation.

Evidence: [catalog implementation](../implementation.md) and
[`test__CatalogSchema.py`](../../../../../../tests/test__CatalogSchema.py).
