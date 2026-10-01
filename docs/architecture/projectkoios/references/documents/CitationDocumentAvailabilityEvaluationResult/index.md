# `CitationDocumentAvailabilityEvaluationResult`

Immutable replay-valid Result retaining the exact availability Request and one
existing `CitationSourceDocumentObservation` per target key in owner order. Its
identity directly binds the target projection ID, plan ID, coverage ID, and
derived observation IDs. Only negative observation IDs replayed from this
Result can authorize `not-observed` in the document projector.

- [Module index](../index.md)
- [Implementation](../implementation.md)
- source: [`availability.py`](../../../../../../src/python/projectkoios/references/documents/availability.py)
- tests: [`test__CitationDocumentProjection.py`](../../../../../../tests/test__CitationDocumentProjection.py)
