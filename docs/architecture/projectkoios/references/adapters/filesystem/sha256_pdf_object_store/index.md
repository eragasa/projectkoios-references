# `projectkoios.references.adapters.filesystem.sha256_pdf_object_store`

`Sha256PdfObjectStore` owns bounded PDF-byte receipt beneath one explicit
`AuthorizedRoot`. It delegates descriptor-confined no-replace publication to
`AuthorizedRoot.write_stream_addressed`, requires `%PDF-`, and returns only
digest, byte size, and create/deduplicate disposition to the owning operation.

It never returns a path through the Web-facing result and never binds a citekey.

## Class

- [`Sha256PdfObjectStore`](Sha256PdfObjectStore/index.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [Operator operations](../../../../../../document-reference-operations.md)
- source: [`sha256_pdf_object_store.py`](../../../../../../../src/python/projectkoios/references/adapters/filesystem/sha256_pdf_object_store.py)
- tests: [`test__DocumentReferenceOperations.py`](../../../../../../../tests/package/projectkoios/references/document_reference/test__DocumentReferenceOperations.py)
- [References architecture](../../../index.md)
