# Reference asset heuristics and canonical materialization

## Authority boundary

Asset discovery observes local PDF bytes and filename/title relationships. It does
not verify bibliographic identity, choose a canonical asset, accept a reference,
clear rights, validate scientific content, authorize manuscript use, accept a
contract, or authorize publication. An exact `citekey.pdf` filename is only a
typed heuristic observation and remains unresolved even when its PDF header,
size, and SHA-256 digest were processed successfully.

`AssetDiscoveryPlan` schema 4 removes the former `score`, `evidence`,
`recommendation`, and `strong-candidate` surface. Every `AssetCandidate` instead
contains:

- the exact unaccepted candidate identity and proposed noncanonical citekey;
- a privacy-reduced root alias and relative path;
- PDF byte size and SHA-256 digest;
- `match_status=unresolved-heuristic-observation`; and
- sorted `AssetHeuristicObservation` values for exact proposed-key filename,
  proposed-key containment, title-token overlap, and year-token presence.

No heuristic kind, number of observations, processing outcome, or successful
scan changes `match_status`. Wrong-content bytes under an exact-looking filename
therefore remain unresolved.

## Ambiguity and deterministic retention

The plan retains every bounded candidate association. It does not choose the
first or best-looking path. `ambiguity_status(candidate_id)` distinguishes a
single unresolved heuristic candidate, competing bibliographic candidates,
alternate source versions, and the combination of both. Candidate ordering,
observation identities, plan identity, and JSON serialization are deterministic.
Absolute private roots are excluded.

State projection records the typed heuristic observations, ambiguity status,
competing observation identities, and alternate-version observation identities.
Multiple values remain discrepancies. Collection reconciliation reports a
single plan candidate as `located-unverified` and competing/versioned candidates
as `ambiguous-matches`; it does not promote either result. The complete plan is
bound into the reconciliation package as an exact input.

`assets-record-plan` records every plan candidate as
`unresolved-heuristic-observation`. It no longer filters a score-selected subset.
SQLite catalog schema 5 remains a rebuildable working projection: importing a
plan does not establish canonical identity and conflicting rows still fail
closed under the existing append/no-overwrite rules.

## Canonical asset authorization

Canonical-name materialization requires both:

1. a replay-validated `IdentityProjection` with one active accepted reference
   and one active canonical citekey; and
2. a separate `CanonicalAssetAuthorization` made by an exactly identified
   person with `reference-identity-curator` scope.

The authorization binds the exact plan identity, identity-projection identity,
active reference, active canonical citekey, selected asset-observation identity,
and a sorted disposition for every connected accepted candidate, competing
candidate, and alternate version. Exactly one disposition authorizes canonical
content. Every retained alternate or rejection has a bounded non-empty rationale.
A stale name, different plan, different projection, omitted competitor, or
unselected asset fails before a filesystem root is opened.

`assets-apply` therefore requires canonical authorization and identity-projection
JSON inputs. It rechecks placeholder preflight, PDF header, byte size, and hash
before destination mutation, then atomically publishes `<canonical-citekey>.pdf`
without replacing different bytes. Existing identical bytes are idempotent.
When catalog recording is requested, the command holds a schema-validated
write transaction across materialization. Candidate existence and exact
conflict/idempotence semantics are checked before the destination is touched;
the write lock prevents another catalog writer from invalidating that preflight.
If post-materialization validation or commit fails, only a newly created file
whose size and SHA-256 still exactly match the authorized bytes is removed.
A pre-existing identical file is never removed. If exact rollback itself cannot
be proved, the command reports both failures rather than deleting changed bytes.
Rights and publication authority remain outside this decision.

## Safety, limits, and compatibility

Discovery and apply retain the bounded-I/O profile, descriptor-confined path
checks, explicit storage classes, cloud-placeholder preflight, symlink rejection,
streaming copy, fsync, and atomic no-overwrite publication established by
REF-CLOUD-SAFETY-01 and REF-IO-BOUNDS-01. Tests use only sanitized synthetic
fixtures and injected probes.

Schema-3 plans are rejected. They contain score/recommendation semantics and no
typed non-authoritative heuristic contract, so schema 4 cannot infer an
authorization or migrate them implicitly. No catalog migration is required;
catalog schema 5 and its explicit migration policy are unchanged.
