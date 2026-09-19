# Literature-review ingestion

## Two-tier strategy

Project Koios separates citation-graph expansion from full-document ingestion.

### Tier 1: candidate graph node

A work discovered in a bibliography initially receives only:

- a local candidate identifier;
- proposed citation key;
- title, authors, year, and persistent identifier when available;
- the `cites` edge and its locator in the parent source;
- metadata-verification status; and
- an optional abstract with its own source and retrieval status.

An abstract is useful for screening but is not required for graph membership. It
must not be treated as evidence for detailed claims or as proof that the full
work has been read. If a metadata provider supplies no abstract, the field stays
empty rather than being generated or inferred.

### Tier 2: selected full source

A candidate is promoted only when it is relevant to an explicit review
question. Promotion may add:

- a verified canonical BibLaTeX record;
- a lawfully held `<citekey>.pdf` source asset;
- a `<citekey>.md` reference note;
- a page-anchored transcription;
- preserved tables, equations, figure captions, and necessary figures;
- claim-to-locator evidence records; and
- backward and forward citation expansion.

## Transcription requirements

A transcription records its method and completeness. Raw machine extraction,
structured normalization, critical reading, and human acceptance are distinct
states.

Page boundaries use explicit source-page and PDF-page anchors. Mathematical
symbols and equations are checked against the rendered page. Tables are
represented as Markdown when their structure can be preserved. Necessary
figures use `<citekey>-figure-NN` filenames and retain checksums and source-page
provenance.

The original PDF remains the source authority. A transcription must never hide
uncertainty introduced by OCR, text extraction, column ordering, dehyphenation,
or equation reconstruction.

## Rights boundary

Openly licensed sources may be transcribed and transformed under their license
with attribution. Full transcriptions and extracted figures from sources whose
redistribution rights are unclear remain private local working material. Tracked
catalogs contain metadata, statuses, and checksums rather than restricted source
content.

## Implemented execution path

The first reusable path is split across repository boundaries:

```text
koios-ref
    -> bibliography catalog, asset plan, citation graph, enrichment
koios-ingest-pdf
    -> destination-independent cold extraction and raw page artifacts
koios-obsidian-note
    -> protected-section note projection after explicit apply
```

Local SQLite catalogs, provider caches, discovery plans, acquisition manifests, and cold-extraction artifacts live under ignored `.koios/` directories. The final Markdown note and key-named PDF remain application-owned vault projections.

References does not inspect that local ingestion layout. Reconciliation accepts
only explicitly injected canonical reference-evidence records, validates each
against the actual managed PDF identity, and preserves recorded producer audit
status separately from independent revalidation. See
[Ingestion reference-evidence consumer](ingestion-reference-evidence.md).

`koios-ref acquisition-create` replaces source-specific manifest scripts for
recurring full-source acquisition. Its version-4 immutable manifest hashes
already held root-relative PDFs, content-identifies normalized input and the
complete manifest, and retains separate typed acquisition, access, and rights
observations alongside proposed identity and source metadata. Atomic
publication accepts only a byte-identical replay; it never repairs or replaces
a different existing output. `koios-ref acquisition-verify` streams and
rechecks every bound source before downstream use. These commands neither
retrieve a source, independently verify a rights assertion, accept manuscript
use, nor convert `unaccepted-candidate` into an accepted reference. See the
Proposed [acquisition-observation contract](contracts/acquisition-observation.md).

The initial implementation does not yet perform OCR, equation recognition,
table reconstruction, semantic figure selection, or automatic recursive
citation extraction. Those operations remain bounded processors or reviewed
proposals rather than hidden behavior in the cold extractor.

## Human-review boundary

Agents may extract, normalize, propose links, and populate candidate graph
nodes. A human decides whether metadata is correct, whether a work is relevant,
whether the transcription is faithful, and whether a source supports a
scientific claim.
