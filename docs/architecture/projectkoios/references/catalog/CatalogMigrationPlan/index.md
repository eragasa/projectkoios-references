# `CatalogMigrationPlan`

Frozen description of one recognized legacy-to-current migration. It records
source and target versions and fingerprints, the recognized source kind, the
backup requirement, and the explicit no-authority-upgrade effect. Planning does
not mutate the database.

Evidence: [catalog implementation](../implementation.md) and
[`test__CatalogSchema.py`](../../../../../../tests/test__CatalogSchema.py).
