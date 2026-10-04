# `CatalogError`

Base `ValueError` for fail-closed catalog operations. It classifies catalog
validation and conflict failures without converting the rebuildable catalog
into an authority source.

Evidence: [catalog implementation](../implementation.md) and
[`test__CatalogSchema.py`](../../../../../../tests/test__CatalogSchema.py).
