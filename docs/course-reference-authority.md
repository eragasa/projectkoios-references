# Course reference authority review

`projectkoios.references.course-reference-authority@0.1.0` is the References-owned
review and replay contract used to resolve a Courses-owned reference selection.
It does not make Courses, API, Web, Search, a bibliography file, or a legacy
catalog row an authority for bibliographic identity.

## Owner boundary

Courses supplies an ordered `CourseReferenceLocatorBinding` tuple and immutable
course selections. `CourseReferenceSelectionEvidence` preserves each scope,
selection, locator-binding, ordinal, display citekey, display status, and opaque
References locator. References verifies the locator-binding identity defined by
the Courses 1.0 contract. The display citekey remains only an observed or
proposed navigation value.

References owns:

- exact source observations and normalized candidates;
- accepted bibliographic-work identity and active citekey;
- canonical source-asset linkage;
- append-only human decisions and deterministic state replay;
- the reviewed course tuple and Search authority projection.

API and Web may transport these objects and their CAS values. They must not
recompute allowed actions, choose identity targets, or infer authority. Search
consumes only complete replay-current authority bindings.

## Queue

`CourseReferenceAuthorityProjector` produces an explicitly labeled `CONTROL`
queue and resolves every opaque locator to exactly one rendered entry and
candidate. It fails closed on missing locators, display-key
mismatch, ambiguous candidates, invalid Courses bindings, or ambiguous active
schema-5 projections. The queue preserves Courses order and contains:

- exact observed-entry identities, byte sizes, and source/revision/digest
  provenance, with source paths and verbatim bytes omitted;
- the separate TeX-safe rendered candidate identity, byte digest/size, and
  normalized fields, with rendered bytes omitted;
- typed exact-key/byte and conflict relations to non-authoritative record
  observations;
- current schema-5 human-decision heads and accepted state projections;
- path-free asset digest, size, rights/status, runtime, document-binding, and
  ingestion evidence;
- owner-computed allowed identity and asset actions;
- content-derived queue and item revision identities.

Reference-record observations never enable `ACCEPT_EXISTING` or `MERGE`. Those
actions may target only replay-current accepted schema-5 state projections. With
no such projections, both actions are unavailable.

The queue object contains no filesystem root, source path, catalog location,
asset relative path, verbatim/rendered entry bytes, discrepancy-record bytes,
free-text decision rationale, or complete decision evidence list. The input
request may contain owner-private exact source provenance; it is deliberately
not embedded in the queue output.

## Sequential decisions

Identity decisions use the closed set:

- `ACCEPT_EXISTING`
- `ACCEPT_NEW`
- `MERGE`
- `REJECT`
- `DEFER`

The first four are global References identity decisions. `DEFER` is recorded in
the course context and never changes global identity authority. Accepting a new
candidate produces a content-derived bibliographic-work identity. Accepting an
existing work or merging requires an explicit active schema-5 target. A merge
retains a distinct proposed key as an alias; it does not silently overwrite an
existing record.

Canonical-asset decisions are a distinct later stream with `AUTHORIZE`,
`REJECT`, and `DEFER`. They are unavailable until identity is accepted.
`AUTHORIZE` requires an exact asset observation with fresh `available` runtime
evidence. Asset authorization establishes the selected source linkage only. It
does not grant rights, publication approval, scientific claim support, or
manuscript authority.

## Persistence and concurrency

`ReferenceAuthorityDecisionAppender` creates typed `HumanReviewDecision`
records and replay-derived `ReferenceStateProjection` values. Its repository
protocol is implemented by schema-5 `ReferenceCatalog` using the existing:

- `source_bibliography_observations` and `reference_candidates` intake tables;
- `human_review_decisions` append-only history;
- `reference_state_projections` replay artifacts;
- `candidate_source_assets` evidence rows.

No schema change, mutable current-state row, document-reference v2 store,
legacy-facade write, or dual write is used.

Every append checks the expected item revision, decision-stream head, complete
state-projection set, and candidate asset-plan set. Exact retries are idempotent.
A stale head or stale evidence set aborts the owner transaction. For
`ACCEPT_NEW`, exact observation/candidate insertion and decision/projection
append occur in the same transaction, so a failed append leaves no partially
inserted inline candidate.

## Replay outputs

Identity replay may establish:

- `bibliographic_work_id`;
- explicit `identity_status = accepted`;
- active and alias citekeys;
- the controlling identity decision.

A later asset replay may additionally establish:

- `source_asset_id`;
- the controlling canonical-asset decision;
- the work-to-source authority binding.

`project_reviewed_course_references` fails unless every selected item has both
stages, then returns the exact Courses order and original locator-binding IDs
alongside accepted work/citekey/source authority. This is the tuple API should
compose with the Courses projector.

`project_search_reference_authority` emits only replay-current complete
bindings. Each result identifies the accepted work and citekey, canonical source
asset, both decisions, exact authority evidence IDs, authority binding, state
projection, and content-derived result. Superseding either decision removes
stale authority on replay rather
than mutating old history.
