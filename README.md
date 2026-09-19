# projectkoios-references

Reference management and citation handling for Project Koios.

## Prototype status

The integrated command set remains a pre-release prototype under adversarial
remediation. It is not yet a safe generic scanner, final missing-PDF census,
canonical-promotion gate, accepted ingestion interface, or accepted
cross-repository reconciliation contract. Each use must follow the open owner
issues and supplied-root limitations; failed or absent evidence must not be
promoted into an availability, rights, relevance, or scientific claim.

The canonical reference convention uses one accepted BibLaTeX citation key as
the basename of both the reference note and local PDF. See
[Reference object convention](docs/reference-object-convention.md),
[Reference identity and authority](docs/reference-identity.md),
[Literature-review ingestion](docs/literature-review-ingestion.md),
[PDF coverage observations](docs/coverage-observations.md), the
[reconciliation package model](docs/reconciliation-packages.md), the
[ingestion reference-evidence consumer](docs/ingestion-reference-evidence.md),
the [source-backed citation graph](docs/citation-graph.md), the
[actor-provenanced review-state model](docs/review-state.md), the
[reference working catalog](docs/reference-catalog.md), the
[bounded reference-I/O policy](docs/reference-io-bounds.md), and
[cloud-placeholder safety](docs/cloud-placeholder-safety.md). Remaining metadata
and validation work is decomposed in the
[citation and review backlog](docs/tasks/citation-review-backlog.md).

The initial [`ksdft2effmass` review seed](collections/ksdft2effmass/README.md)
preserves the external application's citation keys and records a conservative,
read-only local PDF discovery pass.

The `koios-ref` CLI provides the first reusable operational slice:

```bash
koios-ref catalog-init .koios/references.sqlite3 \
  --catalog-storage-class local
koios-ref bib-import .koios/references.sqlite3 references.bib \
  --source-id example --source-revision REV \
  --catalog-storage-class local --bibliography-storage-class local
koios-ref assets-scan references.bib .koios/assets.json \
  --search-root local:papers=/path/to/local-staging \
  --bibliography-storage-class local --output-storage-class local
koios-ref graph-import .koios/references.sqlite3 \
  sources.csv nodes.csv edges.csv --catalog-storage-class local \
  --sources-storage-class local --nodes-storage-class local \
  --edges-storage-class local
koios-ref assets-record-plan .koios/references.sqlite3 .koios/assets.json \
  --catalog-storage-class local --plan-storage-class local
koios-ref acquisition-create acquisition.csv .koios/acquisition.json \
  --source-id operator-recommendation \
  --metadata-storage-class local --output-storage-class local \
  --source-root local:staging=/path/to/local-staging
koios-ref acquisition-verify .koios/acquisition.json \
  --manifest-storage-class local \
  --source-root local:staging=/path/to/local-staging
koios-ref collection-reconcile seed.bib corpus.csv /managed/pdfs \
  .koios/references/example/reconciliation-output \
  --collection-id example --source-revision REV \
  --bibliography-storage-class local --corpus-storage-class local \
  --pdf-storage-class local --output-storage-class local \
  --source-discovery source-discovery.json \
  --source-discovery-storage-class local \
  --coverage-observation coverage-observation.json \
  --coverage-observation-storage-class local \
  --manuscript-root /isolated/source/docs/publications \
  --manuscript-storage-class local \
  --reference-evidence example2026=/explicit/evidence/example2026.json \
  --reference-evidence-storage-class example2026=local
koios-ref validate references.bib /path/to/notes /path/to/pdfs \
  --bibliography-storage-class local \
  --notes-storage-class local --pdf-storage-class local
```

`bib-import` observes exact source entries and projects normalized,
noncanonical candidates into the provisional local catalog. `graph-import`
reads a bounded three-file batch, verifies content-derived source, candidate,
and edge identities and both edge domains, then appends the complete graph in
one transaction. Import, graph membership, asset matching, validation, and
reconciliation do not produce canonical or relevant references; only replay of
a valid actor-provenanced identity decision can produce canonical identity.

The public Python review API keeps processor outcomes, reading, claim-support
checks, and review-collection inclusion in separate immutable records. Complete
replay retains corrected and superseded history and rejects stale concurrent
branches. It cannot represent canonical promotion, scientific acceptance,
manuscript use, rights clearance, or publication as a review status. See
[Actor-provenanced reference review state](docs/review-state.md).

The working catalog supports owner-internal schema version 4 with a deterministic
schema fingerprint and complete observation/candidate/review round trips.
Existing, newer, altered, or incomplete schemas are never silently relabeled.
Recognized synthetic version-1, version-2, and exact version-3 layouts require
an explicit backup-confirmed forward migration through the Python API. Legacy
review scalars remain quarantined without authority upgrade; no operator catalog
is migrated by these commands. See
[Reference working catalog](docs/reference-catalog.md).

`collection-reconcile` creates an immutable, replayable package containing
`package-manifest.json`, `collection-manifest.json`, `citation-closure.json`,
`coverage-observation.json`, `missing-pdfs.csv`, `ambiguous-pdfs.csv`, and
`extra-pdfs.csv`. The package identity binds every payload output and all
consumed evidence bytes. Source-revision labels remain explicitly asserted;
only a matching clean Git `HEAD` can add verified commit and tree identity. See
[Reconciliation packages](docs/reconciliation-packages.md) for the package,
version, authority, verification, and replay boundaries. The command hashes and
header-checks managed PDFs, ignores commented LaTeX citations and macro
placeholders, classifies source/PDF applicability conservatively, and records
metadata, access, rights, ingestion, and transcript status without changing source
bibliographies or assets. Ingestion state is accepted only through explicitly
injected, canonical `projectkoios.ingestion.reference-evidence@0.1.0` bytes that
match the managed PDF digest and size; the command never discovers a producer
workspace or interprets its private filenames. The contract remains Proposed,
and a recorded passing producer audit remains distinct from independent
revalidation. Its candidate-key rows are evidence projections and
do not grant canonical citekey authority. Absence and discovery statuses require a typed,
content-identified coverage observation: no coverage produces
`not-yet-searched`, and incomplete or failed coverage cannot produce
`not-located`. The command does not scan additional roots, hydrate cloud
placeholders, download sources, verify rights, or promote bibliography records.

Asset scans store only search-root aliases and relative paths. Version-3 plans
bind explicit root storage and placeholder-probe evidence, the complete
I/O profile, complete-coverage status, candidate
identity, and explicit noncanonical statuses. A limit diagnostic remains
`incomplete` and is never serialized as a partial plan. Applying a candidate
requires a separate command, rechecks its planned hash, and writes a
candidate-suffixed filename rather than manufacturing a canonical reference
object. Authorized
roots are resolved and identity-bound once; traversal, root replacement, and
symlink files or directories fail closed before bytes are read, hashed, copied,
or reported. Confined writes use no-follow directory descriptors and atomic
same-directory publication. Provider responses are cached locally under
`.koios/` when requested. The immutable provider observation and cache boundary
is documented in
[`docs/reference-metadata-providers.md`](docs/reference-metadata-providers.md).

Recurring lawful acquisition uses a separate version-3 manifest. The manifest
records root storage/probe evidence, complete-coverage status, and the exact
effective I/O-limit profile. Earlier manifests do not contain all of that
evidence and are rejected rather than silently relabeled or assigned inferred
limits.
`acquisition-create` reads bounded CSV metadata, resolves each root-relative PDF
without permitting traversal, streams one size/hash/header observation per
unique source, and records its byte size and SHA-256 identity. Required CSV
columns are `proposed_citekey`, `root_alias`, `relative_path`, `rights_status`,
`asset_status`, and `identity_status`; optional columns are `doi`, `source_url`,
and `source_version`. The only permitted identity status is
`unaccepted-candidate`, so creating or verifying a manifest cannot claim
accepted-reference authority. `acquisition-verify` streams and rechecks every
source. Neither command downloads content, bypasses access controls, verifies
license claims, edits canonical BibLaTeX, or writes a vault.

Repository routing is documented in `projectkoios-bootstrap/maps/repositories.md`.

## Contracts

Authoritative reference contract proposals and accepted contracts are indexed
in [`docs/contracts/README.md`](docs/contracts/README.md).
