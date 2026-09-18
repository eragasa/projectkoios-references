# projectkoios-references

Reference management and citation handling for Project Koios.

## Prototype status

The integrated command set remains a pre-release prototype under adversarial
remediation. It is not yet a safe generic scanner, final missing-PDF census,
canonical-promotion gate, accepted ingestion interface, or complete
content-addressed reconciliation package. Each use must follow the open owner
issues and supplied-root limitations; failed or absent evidence must not be
promoted into an availability, rights, relevance, or scientific claim.

The canonical reference convention uses one accepted BibLaTeX citation key as
the basename of both the reference note and local PDF. See
[Reference object convention](docs/reference-object-convention.md),
[Literature-review ingestion](docs/literature-review-ingestion.md), and the
[reference working catalog](docs/reference-catalog.md). Deferred graph,
metadata, review, and validation work is decomposed in the
[citation and review backlog](docs/tasks/citation-review-backlog.md).

The initial [`ksdft2effmass` review seed](collections/ksdft2effmass/README.md)
preserves the external application's citation keys and records a conservative,
read-only local PDF discovery pass.

The `koios-ref` CLI provides the first reusable operational slice:

```bash
koios-ref catalog-init .koios/references.sqlite3
koios-ref bib-import .koios/references.sqlite3 references.bib \
  --source-id example --source-revision REV
koios-ref assets-scan references.bib .koios/assets.json \
  --search-root papers=/path/to/papers
koios-ref graph-import .koios/references.sqlite3 nodes.csv edges.csv
koios-ref review-import .koios/references.sqlite3 review-id corpus.csv
koios-ref assets-record-plan .koios/references.sqlite3 .koios/assets.json
koios-ref acquisition-create acquisition.csv .koios/acquisition.json \
  --source-id operator-recommendation \
  --source-root staging=/private/staging
koios-ref acquisition-verify .koios/acquisition.json \
  --source-root staging=/private/staging
koios-ref collection-reconcile seed.bib corpus.csv /managed/pdfs \
  .koios/references/example/reconciliation-0.4.0 \
  --collection-id example --source-revision REV \
  --source-discovery source-discovery.json \
  --manuscript-root /isolated/source/docs/publications \
  --ingestion-root /managed/workspace/.koios/ingestion
koios-ref validate references.bib /path/to/notes /path/to/pdfs
```

`collection-reconcile` creates immutable, replayable
`collection-manifest.json`, `citation-closure.json`, `missing-pdfs.csv`,
`ambiguous-pdfs.csv`, and `extra-pdfs.csv` outputs. It hashes and header-checks
managed PDFs, ignores commented LaTeX citations and macro placeholders,
classifies source/PDF applicability conservatively, and records metadata,
access, rights, ingestion, and transcript status without changing source
bibliographies or assets. Its absence claims are limited to the supplied
managed directory and privacy-reduced discovery evidence; it does not scan
other roots, hydrate cloud placeholders, download sources, verify rights, or
promote bibliography records.

Asset scans store only search-root aliases and relative paths. Applying a
candidate requires a separate command and rechecks its planned hash. Authorized
roots are resolved and identity-bound once; traversal, root replacement, and
symlink files or directories fail closed before bytes are read, hashed, copied,
or reported. Confined writes use no-follow directory descriptors and atomic
same-directory publication. Provider responses are cached locally under
`.koios/` when requested.

Recurring lawful acquisition uses a separate version-1 manifest. `acquisition-create` reads CSV metadata, resolves each root-relative PDF without permitting traversal, verifies a PDF header, and records its byte size and SHA-256 identity. Required CSV columns are `proposed_citekey`, `root_alias`, `relative_path`, `rights_status`, `asset_status`, and `identity_status`; optional columns are `doi`, `source_url`, and `source_version`. Identity status is either `accepted-reference` or `unaccepted-candidate`, so creating or verifying a manifest never promotes a candidate. `acquisition-verify` rechecks all source bytes. Neither command downloads content, bypasses access controls, verifies license claims, edits canonical BibLaTeX, or writes a vault.

Repository routing is documented in `projectkoios-bootstrap/maps/repositories.md`.

## Contracts

Authoritative reference contract proposals and accepted contracts are indexed
in [`docs/contracts/README.md`](docs/contracts/README.md).
