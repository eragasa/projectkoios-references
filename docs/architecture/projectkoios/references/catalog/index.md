# `projectkoios.references.catalog`

This package owns the rebuildable SQLite working projection for reference
identity, assets, review history, state projections, and citation graphs. The
public import path remains `projectkoios.references.catalog`; the package split
does not change the catalog schema, schema fingerprint, migration order,
transaction boundaries, JSON exports, or database compatibility.

## Public classes

- [`CatalogError`](CatalogError/index.md)
- [`CatalogSchemaError`](CatalogSchemaError/index.md)
- [`CatalogMigrationRequired`](CatalogMigrationRequired/index.md)
- [`CatalogConflictError`](CatalogConflictError/index.md)
- [`CandidateConflictError`](CandidateConflictError/index.md)
- [`CatalogSchemaInfo`](CatalogSchemaInfo/index.md)
- [`CatalogMigrationPlan`](CatalogMigrationPlan/index.md)
- [`ReferenceCatalog`](ReferenceCatalog/index.md)

## Authority boundary

The catalog is a non-authoritative, rebuildable working projection. Successful
storage, migration, replay, or export does not grant identity, rights,
scientific, review, Search, ingestion, use, or publication authority.
Authoritative immutable records remain owned by their source contracts.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source: [`catalog`](../../../../../src/python/projectkoios/references/catalog/)
- schema and migration tests: [`test__CatalogSchema.py`](../../../../../tests/test__CatalogSchema.py)
- catalog behavior tests: [`test__ReferenceCatalog.py`](../../../../../tests/test__ReferenceCatalog.py)
- [Package index](../index.md)
