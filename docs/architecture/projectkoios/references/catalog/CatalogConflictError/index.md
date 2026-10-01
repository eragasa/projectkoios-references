# `CatalogConflictError`

`CatalogError` raised when an exact-key write encounters different persisted
evidence. Catalog writes never silently replace a conflicting immutable record.

Evidence: [catalog implementation](../implementation.md) and
[`test__ReferenceCatalog.py`](../../../../../../tests/test__ReferenceCatalog.py).
