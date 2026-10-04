# `projectkoios.references.adapters.sql.sqlite.document_reference_schema`

This module owns the empty SQLite schema for the parallel document/reference
store. `DocumentReferenceSchema` is the executable authority for its bootstrap,
invariants, exact schema verification, and operator verification queries.

## Authority boundary

The schema models PDF documents, immutable receipt/source observations,
references, collections, collection membership and PDF requirement, and
explicit one-to-one bindings. It has no snapshot, projection, workflow,
request, task, or pre-effect-intent records.

It does not migrate or mutate the authoritative schema-5 catalog, import the
107 monograph records, authorize metadata, process documents, build Search
indexes, or authorize a cutover. Schema 5 remains authoritative until an
explicit cutover.

## Class

- [`DocumentReferenceSchema`](DocumentReferenceSchema/index.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [Generated schema note](../../../../../../../document-reference-schema.md)
- source: [`document_reference_schema.py`](../../../../../../../../src/python/projectkoios/references/adapters/sql/sqlite/document_reference_schema.py)
- tests: [`test__DocumentReferenceSchema.py`](../../../../../../../../tests/test__DocumentReferenceSchema.py)
- [References architecture](../../../../index.md)
