# `SqliteDocumentReferenceStore`

Local-root-confined SQLite repository for exact reference/collection
registration, immutable receipt observations, derived missing-PDF results, and
atomic idempotent one-to-one binding.

It does not import records automatically or mutate the authoritative schema-5
catalog.

Evidence: [store implementation](../implementation.md) and [focused tests](../../../../../../../../../tests/package/projectkoios/references/document_reference/test__DocumentReferenceOperations.py).
