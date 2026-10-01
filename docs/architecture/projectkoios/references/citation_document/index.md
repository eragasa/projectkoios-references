# Deprecated `projectkoios.references.citation_document`

This package is an identity-preserving compatibility facade for canonical
[`projectkoios.references.documents`](../documents/index.md). It owns no
implementation, records, validation, identities, or action behavior.

Every retained public attribute resolves to the exact canonical class or
constant. Deprecated submodules likewise contain imports, warnings, and
`__all__` declarations only. New code imports from `documents`, `citations`, or
`bibliography` according to ownership.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source facade: [`citation_document/__init__.py`](../../../../../src/python/projectkoios/references/citation_document/__init__.py)
- compatibility tests: [`test__CitationCompatibilityFacade.py`](../../../../../tests/test__CitationCompatibilityFacade.py)
- [Package index](../index.md)
