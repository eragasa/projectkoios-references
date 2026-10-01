# Citation document control contracts

## Status and durability boundary

This document defines the current canonical, unversioned prototype boundaries
implemented by `projectkoios-references`:

- `projectkoios.references.citation-source-document-link`; and
- `projectkoios.references.citation-document-projection`.

These identities contain no version segment. The Python records contain no
schema or contract-version field. Git retains prototype history. A numbered
format begins only after an explicit external, released, or irreplaceable
durability decision. Neither prototype is an accepted Project Koios contract.

## Scope

The projection consumes a bounded neutral view of one complete citation
snapshot supplied by a target owner. It does not read or parse target files.
The view preserves every literal-key occurrence, exact target bibliography
entry, target-owned source gap, source-relative locator, and content identity.
A separately supplied binding connects each target bibliography entry to one
exact `SourceBibliographyObservation` owned by References.

The projection correlates literal keys with a replay-validated
`IdentityProjection`, reduces bounded source-document observations, and applies
replay-validated `CitationSourceDocumentLinkResult` evidence. It owns no PDF
bytes, private filesystem path, source
custody, rights decision, review state, manuscript-use decision, ingestion
state, transcript state, scientific-support decision, or publication decision.

## Neutral target snapshot projection

Canonical citation inventory records live in
`projectkoios.references.citations`; canonical bibliography binding records and
membership state live in `projectkoios.references.bibliography`.
`projectkoios.references.citation_document` temporarily exposes moved names as
deprecated attributes that preserve exact object identity. New code must use
the canonical packages.

The target projection is complete-or-absent. It has no `incomplete` success
form. A malformed, partial, over-limit, or internally inconsistent input is
rejected rather than projected.

The projection retains:

- the opaque target `snapshot_id`;
- exact bibliography path and content identity;
- ordered occurrence records with literal key, source locator, exact origin
  (`direct`, `eqincite_expansion`, or `citation_todo_expansion`), and target
  indexes;
- lexically ordered groups that partition every occurrence exactly once;
- source-ordered bibliography entries;
- explicit missing, duplicate, and uncited key sets; and
- target-owned source gaps without invented citation keys.

The live target adapter performs only two field renames:
`bibliography_entry_id` to `entry_id` and `bibliography_path` to
`bibliography_source_path`. Complete owner source-file, include, call, todo,
request, and result records remain target-owned and are represented by the
replay-validated opaque snapshot identity rather than copied. Literal citation
keys use the owner's exact ASCII grammar `[A-Za-z0-9._-]{1,200}`; they are data,
not portable filenames. Source locators use bounded, normalized, root-relative
POSIX paths and therefore do not inherit Windows-reserved-name or portable
filesystem mutation policy.

A target bibliography entry may carry a nullable
`source_bibliography_observation_id`. The target owner never fabricates that
identity. References requires a complete aligned tuple of
`CitationBibliographyObservationBinding` objects and independently checks the
exact bibliography digest/size/path/index/key and verbatim-entry digest/size.
A non-null target field must equal the bound observation identity.

## Deterministic literal-key bridge

The projector composes the canonical citation and bibliography resolution
helpers to perform the bridge; Applications, API, and Web must not infer
identity.

1. Replay the supplied `IdentityProjection` and require exact equality.
2. Index active canonical citekeys and active aliases. These accepted names
   take precedence because an accepted reference commonly retains a candidate
   with the same proposed key.
3. For a key without an active accepted name, use only candidates whose
   `source_observation_ids` contain the exact observation bound to a target
   bibliography entry and whose proposed key equals the literal key.
4. One candidate resolves; multiple candidates remain ambiguous with every
   identity retained; no candidate remains unresolved.
5. Inactive historical names are not followed unless replay exposes an active
   alias.
6. Resolve the sorted, deduplicated identity IDs through the existing
   `CitationIdentityProjector`; never invent an identity ID.

Rows are sorted by literal key. Occurrence IDs retain target snapshot order
inside each row. Repeated occurrences are never deduplicated. Bibliography
membership is projected independently as `defined`, `undefined`, or the
reserved `not-evaluated`; it cannot substitute for reference-identity status.

## Document evidence statuses

`CitationDocumentAvailabilityStatus` is closed:

| Status | Meaning |
|---|---|
| `not-evaluated` | No complete absence evidence applies. This includes no observation, incomplete observation, or an unresolved identity with no positive document evidence. |
| `not-observed` | The key resolves and complete bounded evidence explicitly observed no document. This is the only state consumers may label “missing.” |
| `available-unverified-linkage` | One exact PDF content identity is observed for the key, but no valid neutral link is supplied. |
| `available-linked` | One exact PDF content identity has at least one valid neutral link to the exact resolved identity. This is attachment only. |
| `ambiguous` | Competing PDF content identities or contradictory positive/inaccessible evidence remain. |
| `inaccessible` | Explicit bounded evidence reports inaccessible content and no document descriptor is available. |

Multiple locations or document IDs for identical SHA-256 and byte size do not
manufacture independent content. Distinct content identities remain ambiguous.
Input ordering cannot select a winner.

## Neutral source-document link

The link action binds:

- the exact prior citation-document projection and row;
- one exact resolved `CitationIdentityProjectionItem`;
- one exact available `CitationSourceDocumentDescriptor`;
- every matching availability-observation identity;
- an opaque bounded pre-effect application intent identity; and
- `linkage_basis=explicit-upload-for-requested-citation`.

The pre-effect intent is lineage only. References imports no Applications type
and does not interpret application policy. The downstream request or workflow
that consumes the link must not be used as the pre-effect identity; doing so
would create an identity cycle.

Exact replay is idempotent. Changed intent, evidence, descriptor, item, or
projection creates a distinct link. A later competing attachment is retained
as ambiguity and never silently replaces an earlier link.

Every link and projection explicitly deny private-processing and Search
admission. Every link fixes these limitations:

- not canonical-asset authorization;
- not ingestion status;
- not manuscript-use authorization;
- not private-processing admission;
- not publication authorization;
- not a review decision;
- not rights clearance; and
- not scientific support; and
- not Search admission.

## Runtime and persistence boundary

`CitationDocumentProjectionRequest` and `CitationSourceDocumentLinkRequest` are
runtime operation inputs. Projection requests consume exact link results, not
bare links. Both result families replay the one canonical focused builder and
require exact output equality before validating the result identity. The
immutable projection, item, descriptor, observation, and link records are the
current canonical prototype DataObjects. They have stable content identities
but no separately promised wire compatibility. These canonical implementations
are closed value types rather than extension points: they are marked `final` for
static checking, and every runtime composition boundary requires the exact
canonical class. Subclasses cannot override replay validation or add mutable
state to a canonical Request or Result graph.

Absolute paths, PDF bytes, stores, clients, credentials, ingestion records, and
mutable workflow state are prohibited from every References-owned record in
this family.

## Bounds and failure behavior

The implementation bounds occurrences, unique keys, bibliography entries,
source gaps, source documents, links, per-key documents/evidence, identifiers,
normalized relative POSIX source paths, and text before projection. A target source identity and a PDF
descriptor are each at most 100,000,000 bytes; per-record target references are
at most 256; and every canonical identity payload is at most 20,000,000 UTF-8
bytes.
Ordering, duplicate identities, inconsistent
derived key sets, forged identities, replay drift, stale links, mismatched
bibliography bindings, unsupported media, and conflicting descriptors fail
closed.

A quarantine receipt may supply availability evidence. It is not a neutral
link. A neutral link is not source admission. Purpose-specific admission and
permission to process remain decisions of their owning architecture and human
authority.
