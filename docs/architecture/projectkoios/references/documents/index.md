# `projectkoios.references.documents`

This module consumes a bounded neutral projection of one complete target-owned
citation snapshot. It correlates exact literal keys to replay-derived reference
identity and reports orthogonal source-document evidence without reading target
files or owning PDF bytes, rights, review, use, or ingestion state.

## Public classes

- [`CitationDocumentAvailabilityEvaluationRequest`](CitationDocumentAvailabilityEvaluationRequest/index.md)
- [`CitationDocumentAvailabilityEvaluationResult`](CitationDocumentAvailabilityEvaluationResult/index.md)
- [`CitationDocumentAvailabilityEvaluator`](CitationDocumentAvailabilityEvaluator/index.md)
- [`CitationDocumentAvailabilityStatus`](CitationDocumentAvailabilityStatus/index.md)
- [`CitationSourceDocumentDescriptor`](CitationSourceDocumentDescriptor/index.md)
- [`CitationSourceDocumentObservation`](CitationSourceDocumentObservation/index.md)
- [`CitationSourceDocumentLink`](CitationSourceDocumentLink/index.md)
- [`CitationDocumentProjectionItem`](CitationDocumentProjectionItem/index.md)
- [`CitationDocumentProjection`](CitationDocumentProjection/index.md)
- [`CitationDocumentProjectionRequest`](CitationDocumentProjectionRequest/index.md)
- [`CitationDocumentProjectionResult`](CitationDocumentProjectionResult/index.md)
- [`CitationSourceDocumentLinkRequest`](CitationSourceDocumentLinkRequest/index.md)
- [`CitationSourceDocumentLinkResult`](CitationSourceDocumentLinkResult/index.md)
- [`CitationSourceDocumentLinker`](CitationSourceDocumentLinker/index.md)
- [`CitationDocumentProjector`](CitationDocumentProjector/index.md)

## Boundaries

The two prototype contract identities are canonical and unversioned. The
projector consumes canonical [citation inventory](../citations/index.md) and
[bibliography binding](../bibliography/index.md) records through one-way
package dependencies. It preserves every occurrence and source gap, admits no
first-match identity selection, and treats `not-observed` as the only safe
missing-document state. Only the replay-valid availability evaluation Result
can authorize that negative state; arbitrary complete observations cannot. A
neutral link means only that an exact descriptor is attached to an exact
resolved identity.

This canonical facade exports document-owned names only. Citation inventory and
bibliography binding records are imported directly from their canonical owner
packages. Legacy cross-owner aliases exist only on the deprecated
[`citation_document`](../citation_document/index.md) compatibility facade.

See the [citation document control contracts](../../../../contracts/citation-document.md).

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source facade: [`documents/__init__.py`](../../../../../src/python/projectkoios/references/documents/__init__.py)
- tests: [`test__CitationDocumentProjection.py`](../../../../../tests/test__CitationDocumentProjection.py)
- [Package index](../index.md)
