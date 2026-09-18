# Reference working catalog

The reusable working catalog is a provisional SQLite projection. BibLaTeX,
CSV, JSON, and Markdown remain interchange or evidence formats rather than the
sole mutable database.

## Schema version 1

The existing schema-version-1 tables are retained as local implementation
details; no database migration is performed by `REF-IDENTITY-01`. Their legacy
names must not be interpreted as authority. The public API projects:

- normalized, unaccepted candidate records;
- bibliography observations with source identity and asserted revision;
- provider-attributed abstracts;
- unaccepted citation candidates;
- source-located citation edges; and
- source assets associated with proposed keys.

`ReferenceCatalog.import_candidates` accepts `ReferenceCandidate` and
`SourceBibliographyObservation` values. It stores their canonical JSON and
content identities in explicitly named `reference_candidates`,
`source_bibliography_observations`, candidate-to-observation, and
`candidate_source_assets` tables. Candidate asset rows retain both noncanonical
status fields and the candidate identity. The older tables remain adapters for
existing local review and asset operations;
they do not change candidate status. Import cannot create an
`AcceptedReference`. Public counts use `candidate_records` and
`bibliography_observations`; `unprovenanced_alias_rows` is reported only to make
legacy state visible. The old direct alias mutation API is unavailable because
an alias requires an actor-provenanced identity decision.

See [Reference identity and authority](reference-identity.md) for the canonical
decision and replay model.

## Local state

Catalog databases, provider caches, and asset-discovery plans belong under
`.koios/` and are ignored by Git. Deterministic corpus exports may be reviewed
and tracked separately.

Absolute search roots are supplied at execution time. Asset plans contain a
root alias and a relative path so that tracked or shared reports do not expose a
user's home-directory layout.

## Mutation safety

Commands initialize their schema idempotently. Source-asset scans are read-only.
Asset materialization is a separate operation, accepts only strong candidates,
rechecks source size and SHA-256, writes through a temporary file, and refuses
to replace different destination bytes. Materialization does not accept the
candidate or make its proposed citekey canonical.

Network enrichment is explicit and cached. Absence of a provider abstract is
stored as absence; the tool does not generate one.
