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
- [`CitationKeyResolutionStatus`](CitationKeyResolutionStatus/index.md)

## Boundary

`citation_document` depends on these records; this package never imports
`citation_document`. Deprecated attributes on the old facade resolve to these
exact class objects and do not create wrappers or parallel identities.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source facade: [`citations/__init__.py`](../../../../../src/python/projectkoios/references/citations/__init__.py)
- [Package index](../index.md)
