# `CitationIdentityProjector`

Semantic `DataObjectActionizer` with one implementation path:
`action(*, request)` delegates to `project(*, request)`.

The projector builds bounded indexes over an immutable `IdentityProjection`,
rejects ambiguous or contradictory relationships, and emits one correlated item
per requested ID. Candidate lookup is intentionally separate from accepted
reference lookup, so a candidate's proposed key can never appear in the
canonical field even when that candidate participates in an accepted reference.

The performer is stateless and has no filesystem, database, network, workflow,
publication, or target-edit effects.

Evidence: [module implementation](../implementation.md) and
[`test__CitationIdentityProjection.py`](../../../../../../tests/test__CitationIdentityProjection.py).
