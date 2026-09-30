# Project Koios taxonomy inventory

This inventory began at clean baseline `b7581cb` and describes the current
bounded taxonomy milestone in `projectkoios-references`. It does not redefine
cross-repository policy or authorize later persisted-contract changes.

## Dispositions

- **IMPLEMENT_NOW** — safe repository-local work in this milestone.
- **NO_ACTION** — complete for this milestone or intentionally unchanged.
- **DOMAIN_DECISION** — a later request/result identity or action-owner decision
  is required before implementation.

## Package and test inventory

The counts below are top-level source declarations. “Actions” counts public
module functions; public methods on performers and stores are called out below.
“Helpers” counts private module-level functions, not private methods. The
root-facade count includes constants, records, exceptions, and functions.

| Family | Objects | Actions | Helpers | Root facade | Primary tests | Disposition |
|---|---:|---:|---:|---:|---|---|
| `acquisition` | 8 | 3 | 18 | 18 | `test__AcquisitionManifest.py` | DOMAIN_DECISION |
| `assets` | 11 | 3 | 12 | 13 | `test__AssetDiscovery.py` | DOMAIN_DECISION |
| `biblatex` | 3 | 2 | 4 | 2 | `test__BibLaTeXImport.py` | DOMAIN_DECISION |
| `catalog` | 9 | 0 | 15 | 9 | `test__ReferenceCatalog.py`, `test__CatalogSchema.py` | DOMAIN_DECISION |
| `citation_closure` | 11 | 1 | 22 | 13 | `test__CitationClosure.py` | DOMAIN_DECISION |
| `citation_draft` | 8 | 2 deprecated forwards | 0 | 0 | `test__CitationDraft.py` | NO_ACTION |
| `collection_reconciliation` | 15 | 7 | 24 | 19 | `test__CollectionReconciliation.py` | DOMAIN_DECISION |
| `coverage` | 7 public + 1 focused private collaborator | 0 | 0 | 7 | `test__CoverageObservation.py` | NO_ACTION |
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

## Implemented citation-draft families

`CitationDraftEntry` is an immutable, slotted `DataObjectModel` and retains the
existing proposed/noncanonical authority and exact wire fields. Its derived
`entry_id` does not change the citation-draft document schema.

Parsing now has one canonical flow:

```text
CitationDraftParseRequest
  -> CitationDraftParser.action/parse
  -> CitationDraftParseResult
```

Rendering has a separate canonical flow:

```text
CitationDraftRenderRequest
  -> CitationDraftRenderer.action/render
  -> CitationDraftRenderResult
```

Both performers directly inherit the exact `DataObjectActionizer` generic.
`action(*, request)` delegates to the semantic method, and the semantic method
owns the only implementation path. Frozen requests/results have deterministic,
distinct identities that bind their operation contract, input identities,
performer identity, and output identity. Expected malformed-document and
render-limit outcomes retain `CitationDraftError`.

The module has no private module-level helper functions. Entry invariants belong
to `CitationDraftEntry`; parse helpers belong to `CitationDraftParser`; render
helpers belong to `CitationDraftRenderer`. The old module functions
`parse_citation_drafts` and `render_bibtex` remain warning-emitting deprecated
forwarders only. The canonical types remain a module API and were deliberately
not added to the root facade.

## Other object and action boundaries

The unchanged object groups remain immutable observations, records, plans,
projections, manifests, enums, and results. Existing stateful performers/stores
include `AssetDiscoveryPlanner.scan`, `ReferenceCatalog` methods,
`CrossrefClient.fetch`, `ProvidedReferenceIntakeStore` methods, and
`AuthorizedRoot` methods. Other module action entry points still cover
create/load/build/discover/rebind/replay/reconcile/publish/verify/materialize and
validate operations. Those families require their own bounded Request/Result
and persisted-identity decisions; this milestone does not mechanically wrap or
rename them.

`naming` already has the desired ownership shape: immutable
`ReferenceFilenames` owns `from_citekey` and has no free private helpers.
`io_limits` contains intentional reusable public boundary guards. `coverage`
uses the focused `_CoverageDocumentSchema` collaborator and has no module-level
private helpers.

## Dependency identity

The runtime dependency is now intentional and exact:

```text
projectkoios==0.0.0
https://github.com/eragasa/projectkoios.git
commit 233f36900b9b44c943ecc5e27f2968ad4bee97ad
tree b7c3ffd23086e7ef184c990267d48a56dd87282b
```

`pyproject.toml` and `uv.lock` use that immutable revision, not a branch or
machine path. This is a pre-release source identity until a versioned base
package exists. The milestone does not consume the later policy-only commit
`d0cfb06`.

## Initializer, public imports, and operator script

`src/python/projectkoios/references/__init__.py` remains an import-only facade:
19 explicit feature import blocks, one future import, and an explicit 216-name
`__all__`. Imported names and `__all__` agree exactly, with no missing or
duplicate exports. These feature modules remain module-only surfaces:

- `citation_draft`
- `enrichment`
- `validation`

The former `projectkoios.references.cli` package surface no longer exists. The
thin operator adapter is maintained in `scripts/koios_ref.py`; it contains no
private module-level declarations and calls canonical package objects,
including the citation-draft parser and renderer. Packaging includes the
`scripts` package and wires the installed `koios-ref` entry point directly to
`scripts.koios_ref:main`. Tests import that adapter directly. There is no
duplicate package CLI implementation.

Narrowing the 216-name root facade remains a public breaking removal and is not
part of this milestone. Existing semantic performer names and methods remain
non-deprecated. Only the two genuinely superseded citation-draft function entry
points are deprecated.

## Reproduction, safety, and reuse limits

Inventory inputs are repository-tracked Python files under
`src/python/projectkoios/references`, `scripts`, `tests/test*.py`,
`pyproject.toml`, and `uv.lock`. A repeatable syntax-tree inventory can count
top-level classes and public/private functions; import smoke can compare
`set(__all__)` with `dir()`.

Dependency verification must inspect installed `direct_url.json` for the exact
owner commit. Package verification must build offline from the lock, install the
wheel into an isolated Python 3.14 environment with the exact owner source,
confirm `projectkoios.references.cli` is absent, inspect the `koios-ref` entry
point, and run `koios-ref --help` outside the checkout.

This inventory is structural. It does not infer external consumers, modify
unchanged persisted contracts, authorize later action-family migrations, or
prove scientific/reference correctness. Re-run it after public modules,
exports, dependency identity, or maintained tests change; do not reuse the
counts as architecture targets.
