# Course reference authority review

`projectkoios.references.course-reference-authority@0.1.0` is the
References-owned review, append, reread, and replay contract for a Courses-owned
reference scope. It does not make Courses, API, Web, Search, a bibliography
file, or a legacy catalog row authoritative for bibliographic identity.

## Owner boundary

Courses supplies an opaque `CourseReferenceResolutionScopeEvidence` plus the
complete ordered `CourseReferenceSelectionEvidence` tuple. References preserves
and validates, but does not mint or recompute, the Courses-owned scope ID,
manifest ID and digest, inventory ID, total, ordered selection IDs, selection
IDs, ordinals, origins, roles, locator-binding IDs, and opaque References
locators. A display citekey remains a consistency guard only.

References owns:

- exact source observations and normalized candidates;
- rendered-entry-to-candidate identity bindings;
- accepted bibliographic-work identity and active citekey;
- canonical source-asset and typed Ingestion linkage;
- append-only human decisions and deterministic state replay;
- the reviewed course tuple and Search authority projection.

`CourseReferenceAuthorityService` is the API-facing owner seam. API passes the
Courses scope and selection evidence without interpreting it. A configured
References evidence provider loads owner-private render, candidate,
observation, record-discrepancy, runtime-asset, document, and Ingestion
evidence. The service owns schema-5 reads, queue projection, previews, append,
and the post-append owner reread. API and Web may transport returned objects;
they must not query the References catalog, parse private artifacts, recompute
actions, or infer authority.

The concrete owner implementation is
`FilesystemCourseReferenceAuthorityEvidenceProvider`. API supplies only a
`CourseReferenceAuthorityRuntimeConfiguration`: expected course ID, existing
schema-5 catalog path/storage class, and explicit private bibliography source
configurations. `open_course_reference_authority_service` constructs the
catalog reader, provider, and façade without creating or migrating a catalog.
The provider rereads bounded bibliography files, verifies asserted SHA-256
revisions, reconstructs exact observations/candidates/render output, creates
rendered-entry bindings by observation identities rather than citekeys, merges
current schema-5 evidence, and returns path-free owner evidence. Optional typed
runtime asset evidence is accepted only for asset observations still present in
schema 5. Private paths remain runtime configuration and never enter queue or
receipt output.

## Complete left-projected queue

`CourseReferenceAuthorityProjector` produces a `CONTROL` queue containing
exactly one item for every Courses selection in Courses order. The request must
match the scope's exact total and ordered selection-ID envelope. A missing
locator, rendered entry, rendered-entry binding, or candidate does not remove a
Courses item and does not fail the complete queue. Instead that item receives a
closed `CourseReferenceItemResolution` and no mutation actions.

Candidate resolution never joins on a citekey. A content-identified
`RenderedEntryCandidateBinding` binds the opaque locator and rendered-entry ID
to one candidate ID and the exact source-observation inventory. Only after that
identity lookup does References compare the Courses display citekey, rendered
citekey, and candidate proposed citekey as guards.

Resolved queue items contain:

- exact observed-entry identities, sizes, and source/revision/digest
  provenance, with source paths and verbatim bytes omitted;
- the separate TeX-safe rendered candidate identity, digest, size, and
  normalized fields, with rendered bytes omitted;
- typed exact-key/byte and conflict relations to non-authoritative record
  observations;
- current schema-5 decision heads and accepted state projections;
- path-free asset digest, size, rights/status, runtime, document-binding,
  flattened provenance, and typed Ingestion linkage evidence;
- owner-computed allowed identity and asset actions;
- content-derived queue and item revision identities.

Reference-record observations never enable `ACCEPT_EXISTING` or `MERGE`. Those
actions may target only replay-current accepted schema-5 state projections.
The queue contains no filesystem root, source path, catalog location, asset
relative path, bibliography bytes, record bytes, free-text decision rationale,
or complete historical evidence inventory.

Queue projection and service actions reconstruct the request and Courses
locator-binding values. Force-mutated or stale request, scope, selection,
render, binding, runtime, review-head, or projection evidence fails closed.

## Explicit previews and sequential decisions

Identity decisions use the closed set `ACCEPT_EXISTING`, `ACCEPT_NEW`, `MERGE`,
`REJECT`, and `DEFER`. An owner-generated `ReferenceIdentityDecisionPreview`
binds the exact queue and item revisions, disposition, active target when
required, canonical citekey, ordered aliases, selected record-match IDs, and
expected decision-stream head. `DEFER` is recorded only in the course context
and never changes global identity authority.

Canonical-asset review is a distinct later stage. It is unavailable until
identity is accepted. A fresh `CanonicalAssetEvidencePlan` binds the current
identity projection and every current competitor, including rights, runtime
availability/evidence, document evidence, flattened provenance, and typed
Ingestion links. `CanonicalAssetDecisionPreview` requires exactly one explicit
disposition and nonempty rationale for every competitor. `AUTHORIZE` requires
one selected, runtime-available asset. It does not grant rights, publication
approval, scientific claim support, or manuscript authority.

Preview IDs are content-derived owner identities. They are append evidence, not
client-generated hints.

## Typed Ingestion linkage and Search

`IngestionArtifactAuthorityLink` is content identified and exposes exactly the
join fields required to compare References C with Ingestion A/B:

- `source_id`;
- `document_id`;
- `artifact_verification_result_id`.

The link ID is content-derived over all four exact fields. `source_id` itself
retains Ingestion's current bounded opaque identity syntax (including values
such as `source:book`); References does not coerce it into a content-ID alias.
`document_id` and `artifact_verification_result_id` retain their exact current
Ingestion identities. The link also binds the References asset observation.
Flattened document-binding and Ingestion evidence IDs remain replay provenance
and are never join semantics.
An authorized asset with missing, empty, mismatched, or stale typed linkage
remains visible to reference review but is omitted from Search authority.

`project_search_reference_authority` emits only replay-current complete
bindings. Each binding exposes accepted work/citekey authority, the canonical
asset, both controlling decisions, typed Ingestion links, provenance evidence,
the authority binding, and state projection. Superseding either decision
removes stale authority on replay without mutating history.

## Persistence, CAS, and receipts

`ReferenceAuthorityDecisionAppender` creates typed `HumanReviewDecision`
records and replay-derived `ReferenceStateProjection` values. Schema-5
`ReferenceCatalog` implements its repository protocol with the existing source
observation, candidate, source-asset, human-decision, and state-projection
tables. There is no schema change, mutable current-state row,
document-reference v2 store, legacy-facade write, or dual write.

Append CAS covers the preview ID, queue/item revision, exact decision head,
complete projection inventory, candidate/asset observation inventory, and—for
asset review—the complete plan ID containing runtime and typed linkage
evidence. Exact retries are idempotent. Stale or concurrent state aborts the
transaction. For `ACCEPT_NEW`, exact observation/candidate insertion and
decision/projection append are atomic.

An append return becomes a `ReferenceAuthorityDecisionReceipt` only after the
service rereads owner evidence and schema-5 state and verifies the exact current
decision, projection, refreshed queue, and refreshed item. Service failures use
the closed `CourseReferenceAuthorityFailureReason` enum (`COURSE_NOT_FOUND`,
`ITEM_NOT_FOUND`, `EVIDENCE_STALE`, `REVISION_STALE`, `TARGET_STALE`,
`CONCURRENT_DECISION`, `INVALID_DISPOSITION`, `OWNER_MALFORMED`, and
`OWNER_UNAVAILABLE`). API maps the enum and never parses exception text.

## Private exact-scope smoke

The env-gated `test__optional_private_exact_fourteen_smoke` consumes one
untracked mode-0600 JSON capability named by
`PROJECTKOIOS_REFERENCE_AUTHORITY_PRIVATE_SMOKE_JSON`. The capability contains
only runtime source declarations plus the complete opaque Courses scope and
ordered selections; bibliography bytes remain in their private source files.
The test uses the concrete filesystem provider, verifies the expected render
and inventory identities, projects the full queue, and requires exactly 14
items, exact Courses selection order, and `READY` resolution for every item.
No private name, path, or scope payload is committed.

## Reviewed Courses output

`project_reviewed_course_references` fails unless every Courses item has accepted
identity and canonical-asset authority. It then returns the original scope,
selection identity/order, and locator binding alongside accepted work, citekey,
and source authority. Typed Ingestion links are required only by the separate
Search authority projection. Unresolved queue projection itself
remains complete and transportable; it is never shortened to only resolvable
items.
