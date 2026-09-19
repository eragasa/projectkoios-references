# Actor-provenanced reference review state

## Status and authority boundary

This is the bounded owner-internal model implemented for `REF-REVIEW-01`. It
replaces the public mutable `ReviewStatus` / `ReviewMembership` scalar API. It
does not accept a reference, a scientific claim, a manuscript citation, a
rights decision, or a publication action.

The accepted Project Koios reference-authority ADR governs this model. Review
records are immutable, content-addressed history. The SQLite catalog is only a
rebuildable projection. Actor declarations are not self-authenticating: the
repository process admitting a decision must verify that the named actor is the
designated authority for the recorded domain and scope.

## Orthogonal records

`TechnicalReviewRecord` stores one processor outcome for one subject, context,
and technical kind. Discovery, metadata verification, full-text location, and
transcription are separate technical kinds. Their outcomes are observations or
checks only; none means read, relevant, supported, canonical, or accepted.

`HumanReviewDecision` stores one person decision in exactly one dimension:

- `reading` records whether reading is established;
- `claim-support-check` records only that the owning scientific application
  checked claim support; it does not encode or accept a support disposition;
- `review-collection-inclusion` records included, excluded, or unresolved
  membership in a references-owned review collection.

Each record requires a subject content identity, an explicit context, a stable
producing-implementation name and version, actor ID, actor kind, authority
domain and scope, actor-verification record, evidence identities, rationale,
canonical UTC evidence time, the exact effective review-I/O profile and its
content identity, and its own content-derived identity. All of these fields are
bound into the record identity. Actor-verification evidence must be among the
decision evidence.

Technical records require a `processor` actor with `technical-processor`
scope. Human decisions require a `person` actor. Reading and review-collection
inclusion require the corresponding references-owned scope and authority
domain. Claim-support checks require a `scientific-claim-reviewer` scope in a
domain other than `projectkoios-references`; replay records the declared
federated authority but does not designate or authenticate that authority.

## Deliberately separate boundaries

The review model cannot represent the following as review statuses:

| Boundary | Owning record or authority |
|---|---|
| Canonical reference acceptance, merge, split, alias, or rename | `IdentityDecision` and `replay_identity_decisions`; designated human reference curator |
| Scientific relevance or scientific acceptance | Owning research repository or scientific application and its designated human authority |
| Manuscript inclusion, citation, quotation, or reliance | Manuscript-owning repository and designated human author |
| Rights clearance for an action | Repository performing the action and designated human rights authority |
| Publication or release | Publication-artifact owner and designated human publication authority |

Review-collection inclusion is therefore neither scientific relevance nor
manuscript use. A claim-support check is neither a support disposition nor
scientific acceptance. Canonical identity acceptance does not imply either.

## Transition and replay rules

Every stream is keyed independently:

- technical: `(subject_id, context_id, technical_kind)`;
- human: `(subject_id, context_id, dimension)`.

A stream has exactly one `initial` record. Every later `supersession` or
`correction` names the exact current record it replaces and must change the
value. A correction is used when prior evidence or recording was wrong; a
supersession is used when later evidence or a later authorized decision changes
current state. Reading from `read` to `not-established` and claim-support check
from `checked` to `not-established` are regressions and require a correction,
not an ordinary supersession. A child transition timestamp must be equal to or
later than its exact parent timestamp; chronology cannot regress even though a
timestamp remains evidence rather than an authentication mechanism. Both
transition forms retain the replaced record in history. A regression without
exact corrected history is not representable.

`replay_review_records` validates the complete graph and produces one canonical
history order independent of caller input order. It rejects duplicate
identities, missing or cross-stream parents, multiple roots, unchanged
transitions, disconnected history, cycles, and two children of one current
record. The latter is a concurrent-update conflict: neither sibling silently
wins. Callers must preserve both proposals outside authoritative history,
resolve the conflict through the owning human or processor process, and append
one newly evidenced transition.

A replayed `ReviewProjection` contains complete technical and human history plus
current record identities, the fixed replay-producer identity, and the exact
effective limits. Direct construction is prohibited. Parsing a serialized
projection replays only its historical records and requires all derived current
state, producer/limit evidence, and the projection identity to match exactly.

## Bounded parsing

`REVIEW_IO_LIMITS` fixes review JSON at 20,000,000 UTF-8 bytes, nesting depth
64, 4,096 bytes per bounded text field, and 256 replay entries; each record is
further limited to 64 bounded content-identity evidence links. The profile
identity is
`reference-io-limits:sha256:040988955e60b41ba210b5bfc82c199af49414691c7f105d9f113e0d8863f49f`.
Every public JSON parser performs byte and lexical nesting preflight before
`json.loads`.
Oversized or over-depth input raises typed `ReferenceIOLimitError` with
`coverage_status=incomplete`, the exact limit and observation, and the effective
profile identity. Records and replay projections serialize that same profile
and `effective_limits_id`; unsupported or altered profiles fail closed.

## Catalog schema and migration

Published catalog schema 4 added canonical-JSON-backed technical and human
review tables. Current schema 5 preserves those tables unchanged and adds only
the disposable field-level state-projection cache.
`ReferenceCatalog.import_review_records` replays the existing and proposed
records before inserting them in one immediate transaction. Exact replay is
idempotent. Invalid, stale, concurrent, or partially valid batches roll back
without a last-writer update.

Schema 3 is recognized only by its exact predecessor fingerprint
`catalog-schema:sha256:d2970cd39caff4971407ea11b9ab4ea630d53c0b11e1b0dd58a65f045c0bffaa`.
Migration remains explicit and requires `backup_confirmed=True`. It preserves
all schema-3 rows exactly and leaves `legacy_review_memberships` quarantined.
Forward migration from exact published schema 4 preserves every technical and
human review record without relabeling authority.
Even a legacy `human-accepted` scalar is not converted into a human decision or
canonical reference. Existing CSV/JSON corpus reports remain unprovenanced
projections and are not imported into typed review history; they may be retained
or regenerated without upgrading their authority. Unknown, altered, incomplete,
or newer schemas fail closed.

Tests use only sanitized synthetic actors, content identities, catalogs, and
evidence. No operator catalog is opened or migrated by this implementation.
