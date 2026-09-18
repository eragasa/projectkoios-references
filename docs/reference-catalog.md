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
| Owner-internal schema version | `2` |
| Schema fingerprint | `catalog-schema:sha256:2e8db847387f06a003f56c375694000eee5be7edd32d4e7f0712267d1e3d0bc5` |
| Authority boundary | `non-authoritative-rebuildable-working-projection` |

The fingerprint is the SHA-256 identity of a canonical, deterministically
ordered description of every non-SQLite table, explicit index, view, and
trigger in `sqlite_schema`. It covers names, owning tables, object types, and
normalized SQL. It does not hash catalog rows. Missing or extra columns,
indexes, views, or triggers therefore change the fingerprint.

`catalog_metadata` contains exactly `schema_version` and
`schema_fingerprint`. `ReferenceCatalog.initialize()` creates version 2 only
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

Version 2 stores every currently supported
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

Graph tables receive only conflict-aware catalog write semantics here. Stable
graph identities, source/target domain rules, bounds, and source-backed graph
semantics remain owned by `REF-GRAPH-INTEGRITY-01` (#17). Legacy review rows are
append/conflict checked but are not redesigned or granted authority; typed
actor-provenanced review transitions remain owned by `REF-REVIEW-01` (#11).
Field-level state authority and cross-format projection remain owned by
`REF-STATE-PROJECTION-01` (#9).

## Forward-only migration matrix

Only two repository-known synthetic version-1 layouts are recognized:

| Source | Fingerprint | Forward behavior |
|---|---|---|
| Prototype v1 | `catalog-schema:sha256:5714c33eba9eb9638c0735dff5824058d7c77115a3a5c62f97486e0da41d771b` | Preserve every legacy table row in explicitly named `legacy_*` quarantine tables. Create no observations, candidates, aliases, or accepted authority from those rows. |
| Identity v1 | `catalog-schema:sha256:b6280d710df8e1cabdcdec99847a927135a49b9e833d3cb84c5e9bf44ce845c8` | Validate canonical observation/candidate JSON, scalar agreement, links, assets, and foreign keys; expand complete records into v2 columns; preserve all older adapter rows in `legacy_*` quarantine tables. |
| Version 2 | Current fingerprint above | Verify and use unchanged; migration is an idempotent no-op. |
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
