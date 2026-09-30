# `projectkoios.references.citation_identity`

This module projects replay-derived identity state into a bounded,
citation-facing result while preserving the caller's identity correlation and
the exact source `projection_id`. It performs no persistence, serialization,
network access, target inspection, or authority decision.

## Public classes

- [`CitationIdentityProjectionStatus`](CitationIdentityProjectionStatus/index.md)
- [`CitationIdentityProjectionRequest`](CitationIdentityProjectionRequest/index.md)
- [`CitationIdentityProjectionItem`](CitationIdentityProjectionItem/index.md)
- [`CitationIdentityProjectionResult`](CitationIdentityProjectionResult/index.md)
- [`CitationIdentityProjector`](CitationIdentityProjector/index.md)

## Outcomes

The closed statuses distinguish an active accepted reference with its canonical
citekey, a candidate with only its proposed noncanonical key, an inactive
superseded reference, and an unresolved opaque identity. The
accepted-without-active-citekey status is reserved for a future valid replay
state and is unreachable under current replay semantics. A requested candidate
ID remains a candidate even when it participates in an accepted reference.

## Authority boundary

The projection does not decide local-use authorization, scientific support,
target-bibliography presence, citation acceptance, or whether prose should cite
a work. Identity authority remains documented in
[Reference identity and authority](../../../../reference-identity.md); proposed
contract status remains in the
[reference evidence contract](../../../../contracts/reference-evidence.md).

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source: [`citation_identity.py`](../../../../../src/python/projectkoios/references/citation_identity.py)
- tests: [`test__CitationIdentityProjection.py`](../../../../../tests/test__CitationIdentityProjection.py)
- [Package index](../index.md)
