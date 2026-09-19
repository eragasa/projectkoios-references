# Reference state authority and deterministic projections

## Status and authority boundary

This document defines the owner-internal state projection implemented for
`REF-STATE-PROJECTION-01`. It applies the accepted cross-repository reference
authority ADR; it does not expand that ADR, accept a Proposed contract, promote
a reference, clear rights, accept scientific support, authorize manuscript use,
accept a contract, or authorize publication.

Immutable, content-addressed source observations and actor-provenanced human
decisions are historical authority. `ReferenceStateProjection`, SQLite rows,
collection manifests, CSV, BibLaTeX, and JSON exports are deterministic,
disposable views. Rebuilding or deleting a projection does not delete its
inputs. Editing a view does not mutate an input.

## Store classification

| Store | Classification | Authority limit |
|---|---|---|
| `SourceBibliographyObservation`, citation-source records, coverage observations, acquisition-manifest schema 4, source-asset observations, and consumed ingestion reference-evidence records | Immutable authoritative observation for the bounded fact and producer scope stated by that record | An observation does not establish normalized truth, identity promotion, rights clearance, scientific support, manuscript use, contract acceptance, or publication. |
| `HumanReviewDecision` and identity decisions | Immutable historical human decision record; current mutable decision state is replayed through explicit supersession | Authority is limited to the actor's verified domain, scope, context, and dimension. |
| `ReferenceCandidate` | Immutable candidate proposal assembled from exact source observations | The citekey and lifecycle remain `proposed-noncanonical` and `unaccepted-candidate`. |
| Acquisition, asset, and ingestion operational manifests | Authoritative observations only for their declared producer contract and bounded evidence | Private paths are not APIs. Acquisition, access, rights evidence, local possession, and processing status remain separate. |
| SQLite catalog schema 5 | Rebuildable cache and query index | Canonical JSON and exact projection input IDs are validated on every read/write. No row is promotion or last-writer authority. |
| Reconciliation package and collection manifest schema 4 | Immutable package projection | Reports candidate state and discrepancies. It does not resolve them or promote any protected dimension. |
| Canonical state JSON and claim-level CSV | Deterministic projection | Both carry the complete ordered authoritative input IDs and exact per-value input IDs. |
| BibLaTeX output | Deterministic bibliographic projection | Discrepant metadata is omitted. Provenance is emitted in `x-projectkoios-*` fields. Reimport creates a new source observation and cannot update history. |
| Corpus CSV, source-discovery JSON, schema-4 asset plans, and legacy catalog rows | Bounded source observation, discovery proposal, or quarantined compatibility data according to the producing adapter | Filename/title heuristics remain typed unresolved proposals. Human-readable or tracked files are not authoritative merely because of their format. Legacy scalars receive no authority upgrade. |
| Markdown reference objects | Naming or presentation projection | Basenames and rendered text cannot create canonical identity or manuscript acceptance. |

## Executable field authority matrix

`STATE_FIELD_RULES` assigns each supported field exactly one state dimension,
authority owner, and permitted record kind. The matrix covers:

- candidate identity and proposed naming as non-authoritative proposals;
- bibliographic metadata and collection-row observations;
- actor-provenanced reading, claim-check, and collection decisions;
- asset discovery and byte identity;
- acquisition, access, and rights observations;
- ingestion, transcript, producer-contract, and audit observations;
- citation and technical-review outcomes.

Protected canonical-identity, scientific-support, rights-decision,
manuscript-use, publication, and contract-acceptance fields are not accepted by
the generic claim surface at all. Their absence from this references-owned
matrix is not acceptance. Acquisition contract status is separately named
`acquisition_contract_status`; the value
`proposed` cannot become contract acceptance. Acquisition-manifest
`manuscript_status=not-assessed` is a guardrail, not an owning-manuscript
decision, so the state adapter does not project it as manuscript authority.

State knowledge distinguishes `observed`, `unknown`, `not-observed`, and
`not-applicable`. The reducer never interprets one as another.

## Replay and discrepancy rules

`replay_reference_state` accepts typed claims plus the complete declared input
identity set. It sorts inputs, fields, values, record kinds, and locators before
computing a content-derived projection identity. It rejects unsupported fields, field-invalid values, wrong authority owners,
disallowed record kinds, undeclared inputs, malformed content identities,
noncanonical JSON, and incomplete field coverage. Generic claim construction
cannot admit human decisions: only the typed review adapter can translate a
validated `HumanReviewDecision` with actor, authority-scope, and verification
provenance.

For one field:

- no claim projects `not-observed`;
- one distinct value projects `single-authoritative-value`;
- identical values from multiple records project `multi-source-agreement`; and
- distinct values project `unresolved-discrepancy`, retaining every value and
  every exact input identity.

Input order cannot choose a winner. A discrepancy is not resolved by SQLite,
format preference, provider preference, timestamp, import order, or export
order. Resolution that requires judgment must arrive as a separately admitted,
actor-provenanced decision in the owning dimension. Until then, the projection
remains unresolved.

## Format direction and replay

The allowed direction is:

```text
bounded bytes or owner-produced evidence
  -> immutable observation or actor-provenanced decision
  -> typed state claim
  -> deterministic state reducer
  -> SQLite / JSON / CSV / BibLaTeX / reconciliation views
```

Canonical JSON round-trips through `ReferenceStateProjection.from_json` and
must replay byte-identically. Claim-level CSV round-trips through
`projection_from_csv`; projection metadata occurs only in the first row,
per-value provenance remains explicit, and noncanonical row ordering fails.
BibLaTeX is a lossy
metadata view by design: unresolved fields are omitted, and reimport is a new
observation. SQLite retains multiple projection identities for one candidate so
a later import cannot erase an earlier discrepancy-bearing view.

Every state projection records:

- the complete ordered `authoritative_input_ids`;
- the generator name/version, projection schema, and bounded-configuration
  identity;
- every supported field, including fields with no observation;
- per-value input identities, record kinds, and source locators;
- unresolved discrepancies and explicit exclusions; and
- `exact_replay=true`.

## Reconciliation integration

Collection reconciliation accepts optional schema-4 `AcquisitionProjection`
values, one replayed `ReviewProjection`, catalog source-asset records, and an
asset-discovery plan, alongside candidate, collection, coverage, managed-asset,
citation, and ingestion evidence. It emits one state projection per candidate
and a package-bound `reference-state-projections.json`. Catalog assets and asset
plans are explicit bounded inputs; they are never discovered implicitly. Asset
plan JSON must match the producer's canonical bytes exactly, so byte-distinct
JSON cannot collapse into one authoritative plan input. Asset-plan claims retain
typed heuristic observations, competing candidate identities, alternate source
versions, and an unresolved ambiguity status. These proposal claims can create
state discrepancies but cannot create canonical, rights, scientific,
manuscript, publication, or contract authority.

Known acquisition, access, and rights observations replace hard-coded unknowns.
Known actor-provenanced reading decisions are reported separately from the
legacy collection-row reading observation. Parsing a review projection does not
authenticate its actor; the repository process admitting that decision still
owns provenance verification. Asset-byte, acquisition, metadata,
and other conflicting claims remain in `state_discrepancy_fields`; the reducer
does not select one. Each CSV-loaded collection-row observation is bound to the
exact source-byte content ID, zero-based row index, parser identity, and parsed
values; byte-distinct CSV inputs therefore remain distinguishable even when
normalization yields the same values. Each manifest row links to its exact
`state_projection_id`.

Reconciliation continues to report only candidate identity. It does not promote
identity, scientific support, rights clearance, manuscript use, publication, or
contract status.

## Bounds, privacy, and migration

State parsing bounds text, values, claims, authoritative inputs, exclusions,
aggregate serialized projection bytes, CSV output/input bytes, and CSV rows.
Iterable inputs are prefix-bounded before materialization. Catalog projection
imports, reads, and aggregate exports have independent count and total-byte
ceilings. Existing
path authorization, explicit storage-class declarations, cloud-placeholder
preflight, and no-implicit-hydration behavior apply to CLI acquisition and review
inputs. Shared projections retain aliases and relative paths, never absolute
private roots.

Catalog schema 5 adds only the `reference_state_projections` cache table.
Published schema 4 is recognized by exact fingerprint and requires explicit
forward migration with `backup_confirmed=True`. Migration validates and
preserves all schema-4 candidate, citation, legacy, technical-review, and human-
decision rows, then creates an empty state-projection cache. Unknown, altered,
incomplete, or newer schemas fail closed. Migration does not synthesize state,
resolve a discrepancy, or upgrade authority.
