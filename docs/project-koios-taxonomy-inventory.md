# Project Koios taxonomy inventory

This inventory is bounded to `projectkoios-references` at clean baseline
`b7581cb`. It records the existing Python package shape before any
`projectkoios.base` inheritance is introduced. It does not redefine the
cross-repository taxonomy or authorize a persisted contract change.

## Dispositions

- **IMPLEMENT_NOW** — safe, repository-local work that does not require a new
  dependency, a public removal, or a domain identity decision.
- **NO_ACTION** — already suitable for this bounded pass, or unsafe to change
  without a separate compatibility migration.
- **DOMAIN_DECISION** — request/result identity, action ownership, or dependency
  ownership must be decided before implementation.

## Package and test inventory

The counts below are top-level source declarations. “Actions” counts public
module functions; public methods on performers and stores are called out in the
notes. “Helpers” counts private module-level functions, not private methods.
The root-facade count includes constants, records, exceptions, and functions.

| Family | Objects | Actions | Helpers | Root facade | Primary tests | Disposition |
|---|---:|---:|---:|---:|---|---|
| `acquisition` | 8 | 3 | 18 | 18 | `test__AcquisitionManifest.py` | DOMAIN_DECISION |
| `assets` | 11 | 3 | 12 | 13 | `test__AssetDiscovery.py` | DOMAIN_DECISION |
| `biblatex` | 3 | 2 | 4 | 2 | `test__BibLaTeXImport.py` | DOMAIN_DECISION |
| `catalog` | 9 | 0 | 15 | 9 | `test__ReferenceCatalog.py`, `test__CatalogSchema.py` | DOMAIN_DECISION |
| `citation_closure` | 11 | 1 | 22 | 13 | `test__CitationClosure.py` | DOMAIN_DECISION |
| `citation_draft` | 2 | 2 | 7 | 0 | `test__CitationDraft.py` | DOMAIN_DECISION |
| `cli` | 0 | 1 | 11 | 0 | command tests across feature files | NO_ACTION |
| `collection_reconciliation` | 15 | 7 | 24 | 19 | `test__CollectionReconciliation.py` | DOMAIN_DECISION |
| `coverage` | 7 public + 1 focused private collaborator | 0 | 0 after this increment | 7 | `test__CoverageObservation.py` | IMPLEMENT_NOW |
| `enrichment` | 24 | 2 | 17 | 0 | `test__MetadataEnrichment.py` | DOMAIN_DECISION |
| `graph` | 7 | 1 | 21 | 8 | `test__CitationGraph.py`, `test__CitationGraphSeed.py` | DOMAIN_DECISION |
| `identity` | 17 | 1 | 28 | 13 | `test__ReferenceIdentity.py` | DOMAIN_DECISION |
| `ingestion_evidence` | 12 | 3 | 19 | 15 | `test__IngestionEvidence.py` | DOMAIN_DECISION |
| `io_limits` | 2 | 3 | 0 | 12 | `test__IOBounds.py` | NO_ACTION |
| `models` | 2 | 1 | 0 | 3 | exercised across catalog/state tests | DOMAIN_DECISION |
| `naming` | 1 | 0 | 0 | 1 | `test__ReferenceFilenames.py` | NO_ACTION |
| `path_safety` | 18 | 9 | 7 | 16 | `test__PathSafety.py`, `test__CloudPlaceholderSafety.py` | DOMAIN_DECISION |
| `pdf_corpus` | 6 | 2 | 21 | 15 | `test__PdfCorpusDiscovery.py` | DOMAIN_DECISION |
| `provided_intake` | 5 | 0 | 11 | 5 | `test__ProvidedReferenceIntake.py` | DOMAIN_DECISION |
| `reconciliation_package` | 8 | 6 | 7 | 3 | `test__ReconciliationPackage.py` | DOMAIN_DECISION |
| `review` | 14 | 1 | 22 | 15 | `test__ReviewState.py` | DOMAIN_DECISION |
| `state_projection` | 10 | 14 | 23 | 29 | `test__StateProjection.py` | DOMAIN_DECISION |
| `validation` | 1 | 1 | 3 | 0 | validation cases in safety tests | DOMAIN_DECISION |

The suite contains 25 maintained `tests/test*.py` files. Cross-family I/O,
placeholder, reconciliation, catalog, and state tests exercise the same public
objects in addition to the primary tests named above.

## Object and action boundaries

The current object groups are:

- immutable observations, records, plans, projections, manifests, enums, and
  results in `acquisition`, `assets`, `coverage`, `graph`, `identity`,
  `ingestion_evidence`, `pdf_corpus`, `review`, and `state_projection`;
- stateful performers/stores at `AssetDiscoveryPlanner.scan`,
  `ReferenceCatalog` methods, `CrossrefClient.fetch`,
  `ProvidedReferenceIntakeStore` methods, and `AuthorizedRoot` methods;
- module action entry points for create/load/parse/build/discover/rebind/replay,
  reconcile/publish/verify/materialize/render/validate operations; and
- transport protocols and transport request/response records confined to the
  metadata provider boundary in `enrichment`.

No concrete class currently inherits `DataObject`, `DataObjectModel`,
`DataObjectActionRequest`, `DataObjectActionResult`, or
`DataObjectActionizer`. No `*Actionizer`, `Utils`, or `Helpers` class exists.
The repository has no `projectkoios` distribution dependency; its only runtime
requirement is `pybtex>=0.25`.

The material module functions generally accept multiple scalar, path, or
record arguments and return an existing record, tuple, bytes value, boolean, or
`None`. They therefore do not yet expose the uniform
`action(*, request)` boundary. Converting them requires coherent immutable
Request/Result types and explicit request/result identity rules, not mechanical
wrapping.

## Initializer and public imports

`src/python/projectkoios/references/__init__.py` is an import-only facade: 19
explicit feature import blocks, one future import, and an explicit 216-name
`__all__`. It contains no domain implementation. Imported names and `__all__`
agree exactly, with no missing or duplicate exports. These modules remain
module-only surfaces:

- `citation_draft`
- `cli`
- `enrichment`
- `validation`

Submodule imports are also used directly by the tests, so root-facade inventory
alone is not a safe consumer inventory. Narrowing the 216-name facade would be
a public breaking removal and is **NO_ACTION** in this pass. Adding new taxonomy
exports is also deferred until their owning action family is defined.

No documented deprecated public type aliases were found. Existing semantic
performer names (`AssetDiscoveryPlanner`, `CrossrefClient`) and semantic methods
(`scan`, `fetch`, `reconcile`, `replay`, and related verbs) must remain
non-deprecated when their families migrate.

## Implement-now increment

`coverage` has no external effect or material action boundary. Its four shared
wire-shape validators were ownerless private module functions. This increment
moves them without changing behavior into the focused private
`_CoverageDocumentSchema` collaborator. The public records, root exports,
serialized schema, content-derived `coverage_id`, exceptions, and call
signatures remain unchanged. The family now has no module-level private helper
functions.

`naming` already has the desired ownership shape: immutable
`ReferenceFilenames` owns `from_citekey`, has no free private helpers, and is an
intentional root export. `io_limits` contains reusable public boundary guards
rather than hidden private implementation helpers. The CLI remains a transport
adapter and should migrate only with the action family it adapts.

## Required domain and dependency decision

ABC inheritance is stopped. Importing the exact taxonomy ABCs would add a new
runtime dependency on the separately released `projectkoios` distribution.
That changes this repository from an independent package into a downstream core
consumer and requires an owner decision about:

1. whether the dependency is intended at all;
2. the supported version range and release compatibility policy;
3. which operation family owns the first Request/Result identities; and
4. whether persisted request/result identities require new contract versions.

Recommended first action-family review after that decision: the module-only
`citation_draft` parser/renderer, because it has a small consumer set (CLI plus
one focused test module). Even there, parse and render are two distinct verbs;
their request/result stems and whether parsed entries or rendered bytes are the
closed result must be decided before code changes. Effectful and persisted
families must follow separately, one coherent family per commit.

## Reproduction and limits

Inventory inputs are repository-tracked Python files under
`src/python/projectkoios/references`, `tests/test*.py`, `pyproject.toml`, and the
root initializer at baseline `b7581cb`. A repeatable syntax-tree inventory can
count top-level `ClassDef`, public/private `FunctionDef`, `ImportFrom`, and the
literal `__all__`; import smoke can compare `set(__all__)` with `dir()`.

The inventory is structural. It does not infer external consumers, approve a
new dependency, define domain identities, modify persisted contracts, or prove
scientific/reference correctness. Re-run it after public modules, exports, or
tests change; do not reuse the counts as architecture targets.
