# `PybtexBibliographyMetadataReader`

**Source:** [`pybtex_metadata_reader.py`](../../../../../../../../src/python/projectkoios/references/adapters/bibliography/pybtex_metadata_reader.py)

Implements the vendor-neutral `BibliographyMetadataReader` protocol through
PyBTeX. Each call parses exactly one declared entry and returns bounded
`ReferenceDisplayMetadata` without leaking parser-owned objects or raw BibTeX.

The reader preserves absent metadata as absent and fails closed on invalid
syntax, citekey mismatch, or unsupported display bounds.

- [Module index](../index.md)
- [Implementation](../implementation.md)
- [Schematic](../schematic.md)
