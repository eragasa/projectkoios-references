# `CitationDocumentAvailabilityEvaluationRequest`

Immutable exact-type Request binding one replay-valid
`CitationTargetSnapshot`, strict `PdfCorpusDiscoveryPlan`, and strict
`CoverageObservation`. Construction requires identical plan/coverage root sets,
exactly one coverage row for every target key, and exact plan-source evidence
for every positive candidate. Its content identity binds the target projection,
discovery plan, coverage observation, and fixed cross-validation policy.

- [Module index](../index.md)
- [Implementation](../implementation.md)
- source: [`availability.py`](../../../../../../src/python/projectkoios/references/documents/availability.py)
- tests: [`test__CitationDocumentProjection.py`](../../../../../../tests/test__CitationDocumentProjection.py)
