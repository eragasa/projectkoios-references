# `projectkoios.references.citation_document`

This module consumes a bounded neutral projection of one complete target-owned
citation snapshot. It correlates exact literal keys to replay-derived reference
identity and reports orthogonal source-document evidence without reading target
files or owning PDF bytes, rights, review, use, or ingestion state.

## Public classes

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
missing-document state. A neutral link means only that an exact descriptor is
attached to an exact resolved identity.

Moved citation and bibliography attributes remain temporarily available from
this facade as deprecated identity-preserving aliases. New code imports them
from their canonical packages.

See the [citation document control contracts](../../../../contracts/citation-document.md).

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source facade: [`citation_document/__init__.py`](../../../../../src/python/projectkoios/references/citation_document/__init__.py)
- tests: [`test__CitationDocumentProjection.py`](../../../../../tests/test__CitationDocumentProjection.py)
- [Package index](../index.md)
