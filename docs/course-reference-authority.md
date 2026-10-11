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

The public owner seam is the typed immutable action boundary under
`projectkoios.references.courses`: every operation accepts one
`DataObjectActionRequest`, is executed by one `DataObjectActionizer`, and
returns one `DataObjectActionResult`. API passes the Courses scope and selection
evidence without interpreting it. The owner-internal
`CourseReferenceAuthorityService` and configured evidence provider load private
render, candidate, observation, record-discrepancy, runtime-asset, document,
and Ingestion evidence; API never receives those internal graphs. References
owns schema-5 reads, queue projection, previews, append, and the post-append
owner reread. API and Web may transport safe action results; they must not query
the References catalog, parse private artifacts, recompute actions, or infer
authority.

The concrete owner implementation is
`FilesystemCourseReferenceAuthorityEvidenceProvider`. API supplies only a
`CourseReferenceAuthorityRuntimeConfiguration`: expected course ID, existing
schema-5 catalog path/storage class, and explicit private bibliography source
configurations. `FilesystemCourseReferenceAuthorityRuntime` constructs the
catalog reader and provider without creating or migrating a catalog, then
exposes only queue, identity-preview, asset-preview, identity-PUT, and asset-PUT
actionizers.
The provider rereads bounded bibliography files, verifies asserted SHA-256
revisions, reconstructs exact observations/candidates/render output, creates
rendered-entry bindings by observation identities rather than citekeys, merges
current schema-5 evidence, and returns path-free owner evidence.
`CourseReferenceAuthorityAssetRoot` declarations let the provider descriptor-
confined-preflight and hash each current schema-5 asset on every load; missing,
changed, unavailable, and available states therefore produce fresh evidence
rather than accepting a startup snapshot. An optional bounded private linkage
JSON path is likewise reread and parsed by References on every load to obtain
exact document/Ingestion links. API supplies paths/root capabilities only and
never constructs `ReferenceAssetAuthorityEvidence`. Cloud-backed roots are
preflighted before byte access, so ambiguous or placeholder state remains
`UNKNOWN` and cannot authorize. Private paths remain runtime configuration and
never enter queue or receipt output.

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

## Stateless HTTP PUT retry

`PutReferenceIdentityDecisionActionizer` and
`PutCanonicalAssetDecisionActionizer` are the stateless composition operations.
Each accepts its matching immutable PUT request, which contains the exact
preview request plus old queue/item CAS values, asset identity/plan CAS values,
actor evidence, the exact References-generated `expected_preview_id`, the safe
preview `expected_preview_result_id`, and one bounded opaque idempotency key.
API does not create or persist an owner preview object; it returns the safe
preview result to its caller and sends the returned preview-result/preview/plan
IDs in the PUT request.

The identity preview's safe consequence surface is `preview_id`, selection and
disposition, target state projection (for reuse/merge), canonical citekey,
complete aliases, selected discrepancy matches, expected decision head, and
its queue/item revision IDs and `result_id`. The asset preview's safe
consequence surface is
`preview_id`, `plan_id`, selection and disposition, identity state projection,
complete competitor disposition/rationale pairs, selected asset observation,
expected decision head, queue/item revision IDs, and `result_id`. These action
results cannot contain an embedded queue, private runtime evidence, filesystem
information, or typed-linkage payload. A separate consequence ID would
duplicate `preview_id`: the
identity preview ID commits the complete identity consequence and CAS inputs;
the asset preview ID commits the complete asset consequence and `plan_id`.

References derives two idempotency content IDs. The idempotency scope binds
operation kind, course scope, selection, and complete actor verification. The
exact request ID additionally binds every action input, caller-visible CAS
value, expected preview ID, and expected safe preview-result ID. Both IDs, the
owner preview ID, the owner
append-request ID, and (for assets) the complete plan ID are retained in
append-only decision evidence; the raw idempotency key is not persisted.

On retry, References checks idempotency history before applying the now-stale
head/queue checks. Exact request reuse reconstructs the original decision result
and projection from schema-5 history, rereads current owner state, and returns a
fresh verified receipt. Reusing the scoped key with any different input fails
with `IDEMPOTENCY_CONFLICT` and performs no mutation. This remains valid after
service/catalog reopen and requires no API-side preview-object storage or
authority inference. On a new mutation, References regenerates the preview and
requires exact equality with `expected_preview_id` before append; mismatch is
`EVIDENCE_STALE`. Exact retries perform history matching first, so the original
preview ID remains usable after the committed decision changes queue state.

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
`OWNER_UNAVAILABLE`, and `IDEMPOTENCY_CONFLICT`). API maps the enum and never
parses exception text.

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
