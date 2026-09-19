# Reference identity and authority

## Status and boundary

This is the bounded pre-release identity model implemented for
`REF-IDENTITY-01`. It is not the Proposed candidate-manifest contract, a
migration of existing data, or an acceptance of any reference. Import,
normalization, discovery, catalog projection, asset matching, and reconciliation
remain non-authoritative operations.

## Distinct records

The Python API keeps these states separate:

1. `SourceBibliographyObservation` records one exact UTF-8 bibliography entry,
   its source bibliography digest and size, source locator, parser identity, and
   caller-asserted source revision. The exact entry text is retained rather
   than reconstructed from normalized metadata.
2. `ReferenceCandidate` records normalized metadata derived from one or more
   observation identities. Its lifecycle is always `unaccepted-candidate`, and
   its key is always `proposed-noncanonical`.
3. `LegacySeedMapping` maps a legacy seed key to a candidate and source
   observation while explicitly recording `canonical_authority` as
   `not-established`.
4. `IdentityDecision` records a person actor, the actor's authority scope and
   verification-record identity, evidence identities, rationale, inputs,
   outputs, and exact superseded decisions.
5. `AcceptedReference` exists only as the result of replaying a valid promotion
   decision. It binds candidate identities to a content-identified reference;
   it is never emitted by import or a similarity heuristic.
6. `CanonicalNameBinding`, `ReferenceAliasBinding`, and
   `ReferenceSupersession` retain citekey, alias, merge, and split history.

All identities are SHA-256 content identities over canonical serialization.
Public evidence and decision constructors validate tuple-backed immutable
state, normalized DOI and key syntax, bounded values, and exact identity
recomputation. Replay-derived accepted-reference, name, alias, supersession,
and projection records are not exported by the package API and reject ordinary
direct construction. They can only be produced by decision replay or strict
projection parsing, which itself performs replay.

## Promotion and replay

`replay_identity_decisions` deterministically applies an ordered decision log.
Supported decisions are:

- promotion of reviewed candidates;
- merge of active accepted references;
- split of one active accepted reference;
- alias creation or replacement; and
- citekey migration with the prior key retained as alias history.

Promotion evidence must include every promoted candidate, each candidate's
source-observation identity, and the actor-verification record. Later decisions
must bind their input references, output candidates, exact active decisions
being superseded, and actor-verification record. Replay rejects missing or
inactive inputs, duplicate active candidates, citekey/alias collisions,
incomplete merge or split lineage, and non-exact supersession history.

`IdentityProjection` rejects ordinary direct construction.
`IdentityProjection.from_json` does not trust serialized derived rows. It
parses only the candidate and decision records, replays them, and requires the
entire canonical projection to be byte-identical. Changed names, aliases,
supersessions, active references, or content identities fail closed.

## Operational adapters

`load_bibliography` returns aligned source observations and candidates. It does
not return accepted references. Asset discovery, object validation, and
collection reconciliation consume those candidates and use proposed keys for
bounded evidence processing only. Asset plans bind the candidate identity and
noncanonical statuses. Materialization writes a candidate-suffixed filename,
not the canonical `citekey.pdf` shape; any later canonical rename requires a
separately authorized identity and file migration.

The schema-version-5 SQLite catalog is a provisional local projection with an
explicit schema fingerprint. `import_candidates` projects complete candidates
and observations without populating quarantined legacy reference rows. Public
counts use candidate and observation terminology, and the old unprovenanced
alias mutation API is not available. Recognized synthetic version-1 layouts
require an explicit backup-confirmed forward migration; no operator database is
migrated by this work. See [Reference working catalog](reference-catalog.md).

Acquisition manifests created by this repository accept only
`unaccepted-candidate` identity status. Recording or verifying an asset never
promotes its candidate.

## Proposed-contract evaluation

This implementation was compared with the Proposed
`projectkoios.references.candidate-manifest@0.1.0` contract. It provides stable
candidate identity, an explicitly noncanonical proposed key, source-verbatim
entry evidence, normalized core fields, candidate lifecycle state, source and
generator identities, and a separate promotion gate.

It does **not** implement the full Proposed manifest. In particular, it does not
yet provide source attribution for every normalized field, complete venue and
edition metadata, work/version relationships, retrieval dates, rights and
access evidence, discrepancy records, local-availability evidence, or proposed
contract metadata and conformance declarations. No conformance claim is made,
and the Proposed contract remains unaccepted. Those gaps cannot be filled by an
identity decision or by this bounded implementation.
