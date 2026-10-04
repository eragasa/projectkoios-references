# `projectkoios.references.adapters.sql.sqlite.document_reference_store`

`SqliteDocumentReferenceStore` implements the owner repository with an explicit
local database-root capability and bounded database leaf name. It initializes
or verifies `DocumentReferenceSchema`, performs exact idempotent registration,
derives missing PDFs through an injected vendor-neutral bibliography metadata
reader, retains receipt observations, and uses `BEGIN IMMEDIATE` for
conflict-safe one-to-one binding.

The adapter does not open or write the schema-5 catalog and contains no import
of the 107 monograph records.

## Class

- [`SqliteDocumentReferenceStore`](SqliteDocumentReferenceStore/index.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [Operator operations](../../../../../../../document-reference-operations.md)
- [Schema module](../document_reference_schema/index.md)
- source: [`document_reference_store.py`](../../../../../../../../src/python/projectkoios/references/adapters/sql/sqlite/document_reference_store.py)
- tests: [`test__DocumentReferenceOperations.py`](../../../../../../../../tests/package/projectkoios/references/document_reference/test__DocumentReferenceOperations.py)
- [References architecture](../../../../index.md)
