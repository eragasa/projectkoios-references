# Document/reference operations

These References-owned operations support a Web “Missing PDFs” page without
making Web or API reproduce persistence joins.

## Composition

Callers provide two explicit local-root capabilities:

- a database root plus bounded `.sqlite3` leaf name and a vendor-neutral
  `BibliographyMetadataReader` for `SqliteDocumentReferenceStore`;
- a PDF-object root plus an explicit `max_pdf_bytes` cap, never greater than
  100,000,000 bytes, for `Sha256PdfObjectStore`.

No operation mutates the schema-5 catalog. The new store is parallel storage
until a separately authorized cutover.

## Collection registration

`record_reference`, `record_collection`, and `record_membership` are exact,
idempotent registration operations. A collection has `collection_id`,
`source_id`, and `source_revision`. Each membership has a citekey and exactly
one `pdf_requirement`: `required` or `not-applicable`.

These methods do not constitute authorization to import the 107 monograph
records. They only define the bounded owner operation for a future authorized
import.

## Missing-PDF query

`ListMissingPdfReferences.action()` accepts
`ListMissingPdfReferencesRequest(collection_id=...)` and returns
`ListMissingPdfReferencesResult` with source/revision provenance, aggregate
counts, and at most 10,000 privacy-reduced rows containing citekey, entry type,
nullable title, bounded authors, nullable year, and requirement. The injected
reader derives these fields from the exact stored BibTeX entry. The current
PyBTeX adapter does not escape parser-owned objects or raw BibTeX through the
owner result.

A missing PDF is derived, never stored:

1. the citekey is a member of the selected collection;
2. its PDF requirement is `required`; and
3. no reference/document binding exists.

## PDF receipt

`ReceivePdf.receive()` takes a typed `ReceivePdfRequest` and a binary stream.
The stream is read incrementally with a hard cap, must begin with `%PDF-`, and
must match any declared byte size. Bytes are SHA-256 hashed and published as
`<sha256>.pdf` with no replacement beneath the authorized object root.
Existing objects are reverified before deduplication succeeds.

Receipt records contain the digest, byte count, and one optional HTTP(S) source
link. A different source link for the same bytes creates another immutable
receipt observation; it does not replace a scalar source field. The result
reports `received`, `source-observation-added`, or `already-present`.

Receipt does not select a citekey, bind a reference, update BibTeX, accept
metadata, assert rights, or schedule processing.

## Explicit binding

`BindPdfToReference.action()` requires collection ID, selected citekey, and an
existing document SHA-256. The collection membership must exist and require a
PDF. One `BEGIN IMMEDIATE` transaction either:

- creates the one-to-one neutral binding and reports `bound`;
- recognizes the exact binding and reports `already-bound`; or
- rolls back and raises a typed unknown-entity or binding-conflict error.

Neither citekey nor document may be rebound implicitly. Upload and binding stay
separate so bytes cannot auto-accept bibliographic metadata.

## Validation

```bash
uv run python -m pytest -q \
  tests/test__DocumentReferenceSchema.py \
  tests/test__DocumentReferenceOperations.py
uv run ruff check src/python tests tools
uv run mypy src/python/projectkoios/references
```
