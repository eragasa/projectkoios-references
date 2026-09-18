# Reference working catalog

The reusable working catalog is SQLite. BibLaTeX, CSV, JSON, and Markdown remain
interchange or projection formats rather than the sole mutable database.

## Schema version 1

The catalog records:

- accepted reference records;
- bibliography occurrences with source identity and revision;
- provider-attributed abstracts;
- unaccepted citation candidates; and
- source-located citation edges.

A citation candidate is deliberately separate from an accepted reference. Its
proposed citekey has no canonical authority until metadata review.

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
to replace different destination bytes.

Network enrichment is explicit and cached. Absence of a provider abstract is
stored as absence; the tool does not generate one.
