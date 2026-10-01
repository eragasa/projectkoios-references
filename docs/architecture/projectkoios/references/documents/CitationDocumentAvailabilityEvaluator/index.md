# `CitationDocumentAvailabilityEvaluator`

Exact-type Actionizer that cross-validates already supplied canonical evidence.
It performs no root scan, store lookup, filename/title/DOI matching, network
request, normalization, or write. Complete scoped negative authority is derived
only from a complete no-skip plan, COMPLETE failure/exclusion-free coverage,
exact roots and target keys, and per-row evidence containing the exact plan ID.

- [Module index](../index.md)
- [Implementation](../implementation.md)
- source: [`availability.py`](../../../../../../src/python/projectkoios/references/documents/availability.py)
- tests: [`test__CitationDocumentProjection.py`](../../../../../../tests/test__CitationDocumentProjection.py)
