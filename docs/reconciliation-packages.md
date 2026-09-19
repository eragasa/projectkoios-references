# Reconciliation packages

## Status and authority boundary

The reconciliation package is a pre-release, owner-internal evidence projection
implemented for `REF-PROVENANCE-01`. Its package-manifest schema version is `1`;
the embedded collection-manifest schema is `4`.
It is not an accepted cross-repository contract, a canonical-reference decision,
an ingestion contract, a rights decision, or a scientific or publication
approval. Bibliography imports used by reconciliation are exact source
observations plus normalized `unaccepted-candidate` records. Reference rows in
the collection manifest carry `proposed_citekey`, `identity_status`, and
`citekey_status`; candidate CSV outputs use the same explicit fields.
Candidate-key rows inside package payloads remain evidence projections; neither
package creation nor verification is a promotion decision.

The accepted Project Koios reference-authority ADR governs the direction of
this projection: bounded evidence is observed, content identified, and reduced
to deterministic outputs. Hashes establish package integrity and identity only;
they do not establish truth, actor authenticity, rights, relevance, or
acceptance.

## Complete package identity

Every reconciliation directory contains `package-manifest.json`. The manifest
binds:

- the exact bibliography bytes;
- the exact collection-row bytes when loaded through the repository parser;
- the exact supplied coverage and legacy discovery documents;
- every managed asset by logical filename, byte size, and SHA-256 digest;
- every citation-source file by relative logical filename, byte size, and
  SHA-256 digest;
- the complete citation-closure record;
- exact explicitly injected canonical ingestion reference-evidence bytes,
  source-bound status projections, and adapter observations under logical names
  rather than producer paths;
- a normalized immutable record of all reconciliation inputs;
- canonical `effective-io-limits` bytes containing the complete profile,
  complete-coverage status, and content-derived profile identity;
- the package distribution version and the reconciliation, bibliography,
  collection-row, discovery, processing, and citation-parser versions; and
- every payload output filename, byte size, and SHA-256 digest.

The payload outputs are `collection-manifest.json`, `citation-closure.json`,
`coverage-observation.json`, `reference-state-projections.json`,
`missing-pdfs.csv`, `ambiguous-pdfs.csv`, and `extra-pdfs.csv`. The manifest does
not recursively list itself: a file cannot
contain its own final digest and size. Instead, its serialization is canonical
and its `reconciliation-package:sha256:...` identity covers all manifest fields.
A byte edit to the manifest is therefore either a different identified manifest
or invalid noncanonical serialization. Verification rejects missing, extra,
changed, malformed, or noncanonical files.

Package schema, generator/package, component, and content identities are
separate fields. These fields are included only to make package replay
identifiable. They do not define API compatibility, claim contract conformance,
or resolve the broader version policy deferred to `REF-PACKAGE-VERSION-01`.

## Asserted and verified source identity

`asserted_source_revision` is always a caller-supplied label. It is never named
or interpreted as a verified revision.

`verified_source_tree` is present only when citation closure is built from a Git
working tree whose asserted revision is a full object ID equal to `HEAD` and
whose repository is clean. The retained value contains the verified commit ID,
tree ID, and verification method. When those checks cannot be completed, the
field is `null`; exact citation-source content hashes are still retained. A
matching-looking caller label cannot by itself populate verified provenance.

## Immutability and replay

Content-identified records use frozen dataclasses, tuples, and an immutable
counts mapping. Identical inputs and versions produce byte-identical payloads
and the same package identity. Any bound input or payload byte change produces a
different package or fails verification.

The Python API provides:

- `parse_reconciliation_package` for strict manifest parsing;
- `verify_reconciliation_package` for directory and optional expected-identity
  verification;
- `replay_reconciliation` for deterministic immutable publication; and
- `publish_reconciliation` for create-once publication.

Replaying an identical package at an existing destination returns `unchanged`.
An incomplete, unexpected, or byte-different destination fails closed and is
not repaired or overwritten.

## Field-level state projections

Collection reconciliation consumes optional schema-4 acquisition projections,
a replayed actor-provenanced review projection, catalog source-asset records,
and an asset-discovery plan in addition to candidate, collection, citation,
coverage, managed-asset, and ingestion evidence. These inputs must be injected
explicitly through bounded, storage-class-declared API/CLI surfaces. It emits one
content-addressed state projection per candidate, links each collection row to
its projection identity, and binds `reference-state-projections.json` into the
package. Known acquisition, access, rights, and reading-decision evidence is no
longer replaced by hard-coded unknowns. Distinct authoritative values remain an
`unresolved-discrepancy`; they are not selected by import order. Schema-4 asset
plans also retain typed unresolved filename/title heuristics, competing
bibliographic candidates, and alternate source versions. Reconciliation reports
that ambiguity and never treats a heuristic or processing outcome as asset
identity authorization. CSV collection
rows retain source-byte identity, row index, parser identity, and parsed values,
so normalization cannot collapse byte-distinct source evidence.

The package continues to report only `unaccepted-candidate` and
`proposed-noncanonical` identity. State projection cannot grant rights, accept
scientific support, authorize manuscript use, accept a contract, or authorize
publication. See [Reference state authority and deterministic projections](reference-state-projections.md).

## Ingestion evidence boundary

Processing status is consumed only through the references-owned strict adapter
for the Proposed `projectkoios.ingestion.reference-evidence@0.1.0` producer
record. Evidence must be explicitly injected and match the managed PDF SHA-256
and byte length. No evidence is represented as
`reference-evidence-not-supplied`; absence never becomes a claim that a private
producer workspace was searched or that ingestion did not occur.

The package retains the record's completed extraction status,
`automated_unreviewed` transcript lineage, recorded passing derivation-audit
scope and coverage, Proposed contract status, and
`independently_revalidated: false`. Package verification does not rerun the
audit or upgrade proofreading, semantic, scientific, rights, reference, or
publication authority. See
[Ingestion reference-evidence consumer](ingestion-reference-evidence.md).
