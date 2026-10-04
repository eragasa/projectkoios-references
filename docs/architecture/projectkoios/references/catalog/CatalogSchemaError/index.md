# `CatalogSchemaError`

`CatalogError` raised when SQLite structure, metadata, canonical stored JSON,
foreign keys, bounds, or replay-derived rows are incompatible with the exact
supported catalog schema.

Evidence: [catalog implementation](../implementation.md) and
[`test__CatalogSchema.py`](../../../../../../tests/test__CatalogSchema.py).
