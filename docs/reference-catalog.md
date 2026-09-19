# Reference working catalog

## Status and authority boundary

The SQLite catalog is a provisional, disposable working projection owned by
`projectkoios-references`. Immutable source observations, candidates, and
actor-provenanced identity decisions remain historical authority. A catalog
row, schema migration, proposed citekey, legacy status, filename, or successful
technical check cannot accept a reference or upgrade another record's
authority.

CSV, JSON, BibLaTeX, and Markdown remain import or export projections rather
than mutable authority. See
[Reference identity and authority](reference-identity.md).

## Supported schema

The only operationally supported catalog schema is:

| Field | Value |
|---|---|
| Owner-internal schema version | `5` |
| Schema fingerprint | `catalog-schema:sha256:151b0ed2340598d367896fdd17b3a3f3d07222f3f12755649f0e2683338caf09` |
| Authority boundary | `non-authoritative-rebuildable-working-projection` |

The fingerprint is the SHA-256 identity of a canonical, deterministically
ordered description of every non-SQLite table, explicit index, view, and
trigger in `sqlite_schema`. It covers names, owning tables, object types, and
normalized SQL. It does not hash catalog rows. Missing or extra columns,
indexes, views, or triggers therefore change the fingerprint.

`catalog_metadata` contains exactly `schema_version` and
`schema_fingerprint`. `ReferenceCatalog.initialize()` creates version 5 only
for a missing or structurally empty database. For an existing database it
verifies metadata, the actual schema fingerprint, foreign keys, canonical
record JSON/content identities, scalar/JSON agreement, candidate-to-observation
links, and candidate-asset linkage. It never overwrites version metadata or
repairs an altered schema.

A newer version, unknown version, altered fingerprint, unreadable metadata,
missing or extra schema object, incomplete schema, or foreign-key/content
inconsistency fails closed with a preservation and explicit-migration or
recovery requirement.

## Lossless candidate projection

Version 4 stores every currently supported
`SourceBibliographyObservation` field, including parser identity, exact
verbatim entry, source locator, asserted revision, whole-bibliography digest and
size, and the exact canonical JSON/content identity.

It stores every currently supported `ReferenceCandidate` field, including
ordered authors, DOI, ISBN, URL, eprint, generator identity, source-observation
links, explicit `unaccepted-candidate` lifecycle, explicit
`proposed-noncanonical` citekey status, and exact canonical JSON/content
identity. Scalar columns are query indexes only; reads require them to agree
exactly with canonical JSON.

`read_observations()`, `read_candidates()`, and `export_identity_json()` return
deterministically identity-sorted projections and validate their content before
returning it. The export identifies the schema fingerprint and its
non-authoritative cache boundary. It is not a candidate-manifest conformance
claim.

## Append and transaction semantics

Catalog writes use explicit transactions. Multi-record candidate, asset,
review-adapter, and graph operations either commit all rows or roll back all
rows. An identical replay is unchanged. A row with the same catalog key but
different content fails as a conflict; no `INSERT OR REPLACE`, last-writer
update, or silent ignore is used.

Candidate import does not populate legacy `reference_records` or interpret
legacy aliases/statuses as accepted authority. Multiple candidates may retain
the same proposed citekey because their content identities remain distinct.
Candidate asset rows must resolve to an existing candidate, repeat its
proposed key and noncanonical statuses exactly, and store a non-negative byte
size as an actual SQLite integer. Floating-point, Boolean, or coercible textual
sizes are unsupported and fail rather than being normalized. Rights and asset
statuses must likewise be bounded, non-empty strings; numeric, Boolean, empty,
or oversized caller values are rejected before SQLite can apply text affinity.

## Review-state projection

Technical outcomes and human decisions are stored in separate canonical-JSON-
backed tables. Producing implementation name/version and effective-limit
identity are stored as query columns and must agree exactly with each immutable
record's canonical JSON. Catalog writes first replay the complete existing and
proposed history, then insert parents before children in one transaction. Exact replay is
idempotent; stale or concurrent siblings, invalid transitions, malformed actor
scope, and partial batches fail without mutation. Current state is derived by
replay and never stored as a replaceable scalar. Legacy review memberships stay
queryable only in their explicitly named quarantine table and receive no
authority upgrade. See
[Actor-provenanced reference review state](review-state.md).

## Field-level state projection cache

Schema 5 stores canonical `ReferenceStateProjection` JSON beside query columns
for projection identity, subject candidate, artifact/schema kind, and the exact
ordered authoritative input identities. Rows are disposable cache artifacts,
not authority. Multiple projection identities for one candidate are retained;
import order cannot overwrite or resolve a discrepancy. Exact replay is
idempotent. Every catalog open and write verifies canonical JSON/scalar
agreement and candidate linkage. See
[Reference state authority and deterministic projections](reference-state-projections.md).

## Citation-graph projection

Citation graph writes accept only a complete, validated `CitationGraph`. Parent
source observations are identified from source ID, asserted revision, safe
relative path, exact SHA-256, and byte size. Candidate identity is the hash of
that exact source-observation identity and its source-verbatim entry locator.
Edge identity additionally covers the candidate target and direct `cites`
relation. A changed source revision, content digest, or locator therefore
creates new evidence instead of rewriting an older row.

The catalog stores canonical JSON beside query columns for sources, candidates,
and edges and validates their exact agreement on every open and write. Foreign
keys cover both edge domains. Whole-graph validation additionally accepts only a wholly empty graph or a
graph in which every candidate and source participates in exactly one
source-consistent direct edge. It rejects duplicate identities and duplicate
source/locator slots and
enforces the hard source, candidate, edge, text, file, and per-source breadth
limits defined in `GraphImportLimits`. A multi-row import inserts sources,
candidates, and edges in one transaction. Exact replay is unchanged; a changed
row under an existing stable identity is a conflict and rolls back the batch.

Source-verbatim entry, identifier, title, authors, and locator fields remain
separate from DOI-normalized and otherwise proposed metadata. All candidate
rows are fixed to `unaccepted-candidate` and
`unaccepted-normalized-proposal`; all edges are fixed to
`source-observed-only`. These records establish only a direct citation
observation. They do not establish review membership, relevance, reading,
claim support, canonical identity, scientific validity, or publication use.
Graph history is append-only. The implementation does not assert supersession
without a separate evidence-backed relation; a later source blob simply creates
new retained observations, candidates, and edges. The CSV contract and hard
limits are documented in [Source-backed citation graph](citation-graph.md).

Mutable version-1 and published-version-2 graph adapter rows migrate only into
explicitly named `legacy_citation_*` quarantine tables. They are not converted
into source-backed graph evidence. Legacy review rows remain quarantined and
cannot be written through the public API. Schema 4 instead projects immutable,
actor-provenanced technical and human review records after complete replay.
See [Actor-provenanced reference review state](review-state.md). Field-level state authority and cross-format projection are implemented by
`REF-STATE-PROJECTION-01` (#9); see
[Reference state authority and deterministic projections](reference-state-projections.md).

## Forward-only migration matrix

Five exact repository-known predecessor layouts are recognized:

| Source | Fingerprint | Forward behavior |
|---|---|---|
| Prototype v1 | `catalog-schema:sha256:5714c33eba9eb9638c0735dff5824058d7c77115a3a5c62f97486e0da41d771b` | Preserve every legacy table row in explicitly named `legacy_*` quarantine tables. Create no observations, candidates, aliases, or accepted authority from those rows. |
| Identity v1 | `catalog-schema:sha256:b6280d710df8e1cabdcdec99847a927135a49b9e833d3cb84c5e9bf44ce845c8` | Validate canonical observation/candidate JSON, scalar agreement, links, assets, and foreign keys; expand complete records into v3 columns; preserve all older adapter rows in `legacy_*` quarantine tables. |
| Published v2 | `catalog-schema:sha256:2e8db847387f06a003f56c375694000eee5be7edd32d4e7f0712267d1e3d0bc5` | Validate and preserve every complete identity/link/asset and legacy row; quarantine mutable graph adapters unchanged in `legacy_citation_*`; create no source-backed graph evidence or authority. |
| Published v3 | `catalog-schema:sha256:d2970cd39caff4971407ea11b9ab4ea630d53c0b11e1b0dd58a65f045c0bffaa` | Validate and preserve every identity, asset, source-backed graph, and legacy row exactly; add empty typed review tables; do not upgrade legacy review scalars. |
| Published v4 | `catalog-schema:sha256:30bb68e78832c461011f7e2a9ba7812c93aa099c866a84869a8415500f415e48` | Validate and preserve every schema-4 candidate, asset, graph, review, decision, and legacy row exactly; add an empty state-projection cache. |
| Version 5 | Current fingerprint above | Verify and use unchanged; migration is an idempotent no-op. |
| Unknown, altered, incomplete, or newer | Any other fingerprint/version | Refuse initialization and migration. Preserve the database for explicit recovery with a compatible implementation or separately reviewed migration. |

Migration is never automatic. `initialize()` reports recognized legacy schemas
as `CatalogMigrationRequired`. `migration_plan()` reports the exact source and
target fingerprints. `migrate(backup_confirmed=True)` is the only forward
migration entry point and accepts only an exact known source fingerprint.

### Backup and preflight

Before calling `migrate` on an operator-owned catalog:

1. stop all catalog writers;
2. create an external byte-preserving backup or work only on a disposable copy;
3. verify that the backup can be opened independently;
4. record the source schema fingerprint and migration plan; and
5. pass `backup_confirmed=True` only after those steps.

The API does not inspect or create private backups and does not treat the caller
flag as backup evidence. This implementation was tested only with synthetic
temporary databases; `REF-CATALOG-01` does not authorize migration of an
existing operator catalog.

### Recovery and rollback

Migration opens one immediate SQLite transaction, validates and snapshots all
known rows, rebuilds the exact target schema, restores rows, writes target
metadata last, then verifies schema fingerprint, foreign keys, canonical
identity records, links, and assets before commit. Any parse, content,
constraint, restore, fingerprint, or induced mid-migration failure rolls back
both DDL and data to the original version-1 database. In particular, an older
candidate asset whose size is stored as SQLite `REAL` is rejected before the
rebuild and leaves the version-1 database unchanged.

Do not edit `schema_version` or `schema_fingerprint` to recover a database. An
unknown or divergent schema requires preservation, a compatible implementation,
or a separately reviewed migration. Dropping columns, tables, indexes,
triggers, or rows is not an authorized repair.

## Local state and privacy

Catalog databases, provider caches, and asset-discovery plans belong under
`.koios/` and are ignored by Git. Tests use only synthetic temporary databases.
Absolute asset roots remain execution inputs; shared catalog projections retain
root aliases and safe relative paths rather than machine-specific private paths.

Network enrichment remains explicit and cached. Absence of provider metadata is
stored as absence; the catalog does not generate metadata, resolve scientific
truth, grant rights, or establish publication authority.
