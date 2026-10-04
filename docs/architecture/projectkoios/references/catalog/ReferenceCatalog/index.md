# `ReferenceCatalog`

Sole public SQLite catalog facade. It authorizes a local path, validates the
exact schema before every operation, provides explicit transactional imports,
reconstructs stored canonical records with semantic replay, exposes deterministic
reads and JSON exports, and performs only explicitly planned known migrations.

The facade remains available from `projectkoios.references.catalog` and
`projectkoios.references`. Package decomposition adds no alternate facade and
changes neither transaction boundaries nor durable schema identity.

The catalog is a rebuildable projection. Its contents do not grant identity,
rights, review, Search, ingestion, use, scientific, or publication authority.

Evidence: [catalog implementation](../implementation.md),
[`test__ReferenceCatalog.py`](../../../../../../tests/test__ReferenceCatalog.py),
and [`test__CatalogSchema.py`](../../../../../../tests/test__CatalogSchema.py).
