# PDF coverage observations

## Status

Implemented pre-release evidence model for `REF-RECONCILE-02`. It does not
accept a reference, authorize a scan, establish rights, or define a final
cross-repository contract.

## Purpose

A managed PDF directory proves only which files are present in that directory.
It cannot establish that a reference was searched for elsewhere or that no
lawful full text exists. Reconciliation therefore consumes a separate,
content-identified `CoverageObservation` when it classifies discovery, access,
or absence.

## Observation identity

A coverage observation records:

- schema version;
- an explicitly **asserted**, not verified, source-revision label;
- state: `not-started`, `complete`, `incomplete`, or `failed`;
- sorted authorized-root aliases;
- sorted exclusions and failures;
- whether ambiguity was evaluated;
- one typed result per observed citekey; and
- `pdf-coverage:sha256:<digest>` identity over the canonical observation.

It never stores an absolute source path. Candidate paths are normalized paths
relative to an authorized root alias.

## Per-reference evidence

Exactly one evidence class is allowed for each observed citekey:

1. `no_match=true`;
2. one or more content-identified candidates; or
3. one access state: cloud placeholder, access controlled, or full text not
   public.

A candidate records its root alias, relative path, SHA-256 digest, byte size,
and whether it is a primary/unknown or alternate version. Duplicate candidates,
conflicting version relations, unauthorized aliases, and mixed evidence classes
fail closed.

## Status rules

Managed bytes take precedence and produce `managed-present` or
`managed-verified` under the existing managed-asset rules. Without managed
bytes, expected-PDF records use these rules:

| Evidence | Result |
|---|---|
| no coverage result | `not-yet-searched` |
| complete coverage + no match | `not-located` |
| incomplete coverage + no match | `search-incomplete` |
| failed coverage + no match | `search-failed` |
| one primary/unknown content identity | `located-unverified` |
| multiple competing content identities, ambiguity evaluated | `ambiguous-matches` |
| alternate candidates only | `alternate-version-only` |
| cloud placeholder | `cloud-placeholder` |
| access-controlled evidence | `access-controlled` |
| full text not public | `full-text-not-public` |

A complete observation must cover every bibliography record supplied to that
reconciliation. Incomplete and failed observations cannot produce
`not-located`. Competing candidates cannot be recorded while ambiguity remains
`not-evaluated`.

Source types classified as non-PDF remain `pdf-not-applicable` unless positive
candidate or access evidence creates an applicability conflict, in which case
the result becomes `pdf-applicability-review` rather than silently discarding
the evidence.

## Outputs

Every reconciliation publishes `coverage-observation.json`. When no observation
was supplied, that output explicitly says `not-supplied` and
`ambiguity_evaluation=not-evaluated`. The collection manifest records the
coverage identity, state, ambiguity-evaluation state, exclusions/failure
counts, and authorized-root aliases. `ambiguous-pdfs.csv` contains actual
competing references only; an empty file is interpreted together with the
explicit ambiguity state.

## Legacy `ksdft2effmass` evidence

The preserved `source-discovery.json` predates this model. Its derived
`coverage-observation.json` is classified `incomplete` because root completion,
cloud-placeholder state, and a competing-candidate inventory were not retained.
The typed projection contains 68 legacy no-match observations. In a bounded
replay with no managed PDFs, 63 expected-PDF records become
`search-incomplete`, five become `pdf-not-applicable`, and the 22 retained
candidates become `located-unverified`. In the separately supplied private
corrected-report evidence, 23 managed seed PDFs leave 62 records classified
`search-incomplete`; no private paths or assets are included here. Neither
replay produces `not-located`. No additional root was scanned and no cloud
object was hydrated to create the projection.
