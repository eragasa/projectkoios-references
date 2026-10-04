# `projectkoios.references.adapters.bibliography.pybtex_metadata_reader`

`PybtexBibliographyMetadataReader` implements the vendor-neutral
`BibliographyMetadataReader` boundary with the repository's existing PyBTeX
dependency. It accepts one exact BibTeX entry and returns only bounded display
metadata: citekey, entry type, title, authors, and year.

The adapter does not expose PyBTeX values, raw BibTeX, paths, source links, or
document identities to callers.

## Class

- [`PybtexBibliographyMetadataReader`](PybtexBibliographyMetadataReader/index.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [Operator operations](../../../../../../document-reference-operations.md)
- source: [`pybtex_metadata_reader.py`](../../../../../../../src/python/projectkoios/references/adapters/bibliography/pybtex_metadata_reader.py)
- tests: [`test__DocumentReferenceOperations.py`](../../../../../../../tests/test__DocumentReferenceOperations.py)
- [References architecture](../../../index.md)
