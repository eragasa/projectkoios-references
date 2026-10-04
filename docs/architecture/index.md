# References component architecture

This navigator covers architecture pages migrated with current implementation
vertical slices. It does not claim repository-wide documentation coverage.
Cross-repository product architecture remains owned by `projectkoios`.

## Documented packages

- [`projectkoios`](projectkoios/index.md)
- [`projectkoios.references`](projectkoios/references/index.md)

The packaged `scripts` package remains outside the migrated slice.

## Current migrated slices

- [`projectkoios.references.citations`](projectkoios/references/citations/index.md)
- [`projectkoios.references.bibliography`](projectkoios/references/bibliography/index.md)
- [`projectkoios.references.citation_identity`](projectkoios/references/citation_identity/index.md)
- [`projectkoios.references.citation_document`](projectkoios/references/citation_document/index.md)
- [`projectkoios.references.catalog`](projectkoios/references/catalog/index.md)
- [`projectkoios.references.collections.reconciliation`](projectkoios/references/collections/reconciliation/index.md)
- [`projectkoios.references.document_reference`](projectkoios/references/document_reference/index.md)
- [`projectkoios.references.path_safety`](projectkoios/references/path_safety/index.md)
- [`projectkoios.references.state_projection_replay`](projectkoios/references/state_projection_replay/index.md)
- [`projectkoios.references.adapters.bibliography.pybtex_metadata_reader`](projectkoios/references/adapters/bibliography/pybtex_metadata_reader/index.md)
- [`projectkoios.references.adapters.filesystem.sha256_pdf_object_store`](projectkoios/references/adapters/filesystem/sha256_pdf_object_store/index.md)
- [`projectkoios.references.adapters.sql.sqlite.document_reference_schema`](projectkoios/references/adapters/sql/sqlite/document_reference_schema/index.md)
- [`projectkoios.references.adapters.sql.sqlite.document_reference_store`](projectkoios/references/adapters/sql/sqlite/document_reference_store/index.md)

The current source tree requires 445 component-architecture pages under the
established convention. These slices supply 196 pages; 249 remain unmigrated.
That count is coverage evidence, not a request for a bulk retrofit.

## Remaining unmigrated modules

- `projectkoios.references.acquisition`
- `projectkoios.references.assets`
- `projectkoios.references.biblatex`
- `projectkoios.references.citation_closure`
- `projectkoios.references.citation_draft`
- `projectkoios.references.coverage`
- `projectkoios.references.enrichment`
- `projectkoios.references.graph`
- `projectkoios.references.identity`
- `projectkoios.references.ingestion_evidence`
- `projectkoios.references.io_limits`
- `projectkoios.references.models`
- `projectkoios.references.naming`
- `projectkoios.references.pdf_corpus`
- `projectkoios.references.provided_intake`
- `projectkoios.references.reconciliation_package`
- `projectkoios.references.review`
- `projectkoios.references.state_projection`
- `projectkoios.references.validation`
- `scripts.koios_ref`
- `scripts.verify_taxonomy_milestone`

[`test__ArchitectureDocumentation.py`](../../tests/test__ArchitectureDocumentation.py)
validates only this touched slice, including exact coverage, links,
reachability, and Mermaid presence.
