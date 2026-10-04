# `projectkoios.references` package

This package owns reference management and citation handling. It distinguishes
bibliographic observations and candidates, accepted identity replay, source
assets, and deterministic projections without deciding scientific support,
manuscript use, rights clearance, or publication acceptance.

## Documented modules

- [`citations`](citations/index.md) — canonical target citation inventory.
- [`bibliography`](bibliography/index.md) — exact bibliography evidence binding
  and membership state.
- [`citation_identity`](citation_identity/index.md) — a
  bounded citation-facing projection over replay-derived identity state.
- [`citation_document`](citation_document/index.md) — deterministic
  whole-target citation correlation and neutral source-document linkage.

## Parallel document/reference adapters

- [`pybtex_metadata_reader`](adapters/bibliography/pybtex_metadata_reader/index.md)
  — PyBTeX implementation of the vendor-neutral display-metadata boundary.
- [`document_reference_schema`](adapters/sql/sqlite/document_reference_schema/index.md)
  — executable empty SQLite schema.
- [`document_reference_store`](adapters/sql/sqlite/document_reference_store/index.md)
  — idempotent collection, receipt, missing-query, and binding persistence.
- [`sha256_pdf_object_store`](adapters/filesystem/sha256_pdf_object_store/index.md)
  — bounded no-replace content-addressed PDF receipt.

The owning `document_reference` module remains outside the completed
architecture-documentation milestone; its focused operator contract is in
[`document-reference-operations.md`](../../../document-reference-operations.md).

All other package modules remain listed as unmigrated in the
[repository navigator](../../index.md).

## Existing authority surfaces

The documented modules consume the current identity implementation rather
than redefining it:

- [Reference identity and authority](../../../reference-identity.md)
- [Reference evidence contracts](../../../contracts/reference-evidence.md)
- [Citation document control contracts](../../../contracts/citation-document.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [`projectkoios` namespace](../index.md)
