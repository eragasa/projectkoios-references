# `projectkoios.references.citations`

This package owns the canonical immutable citation-inventory records copied from
a complete target-owned snapshot. Literal keys remain source data and source
locators remain bounded normalized relative POSIX paths.

## Public classes

- [`CitationContentIdentity`](CitationContentIdentity/index.md)
- [`CitationSourceLocator`](CitationSourceLocator/index.md)
- [`CitationTargetOccurrence`](CitationTargetOccurrence/index.md)
- [`CitationTargetGroup`](CitationTargetGroup/index.md)
- [`CitationTargetBibliographyEntry`](CitationTargetBibliographyEntry/index.md)
- [`CitationTargetSourceGap`](CitationTargetSourceGap/index.md)
- [`CitationTargetSnapshot`](CitationTargetSnapshot/index.md)

## Boundary

These records preserve exact target-owned citation state. They do not project
accepted reference identity or define document processing, availability,
receipts, or target-association policy.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source facade: [`citations/__init__.py`](../../../../../src/python/projectkoios/references/citations/__init__.py)
- [Package index](../index.md)
