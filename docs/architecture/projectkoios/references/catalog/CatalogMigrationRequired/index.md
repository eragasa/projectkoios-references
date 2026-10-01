# `CatalogMigrationRequired`

`CatalogSchemaError` raised for an exactly recognized legacy catalog that must
not be mutated until the caller explicitly inspects a migration plan and invokes
migration.

Evidence: [catalog implementation](../implementation.md) and
[`test__CatalogSchema.py`](../../../../../../tests/test__CatalogSchema.py).
