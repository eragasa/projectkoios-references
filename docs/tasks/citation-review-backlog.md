# Citation and review backlog

## Status and rules

All tasks are proposed. Reference identity, citation discovery, source-asset
presence, abstract screening, reading, claim support, and scientific acceptance
remain separate states.

## Citation graph

### REF-GRAPH-01 — Bibliography observation contract

Define a source-backed bibliography-entry observation containing the parent
source/blob, entry locator, raw text, parsed fields, persistent identifiers,
confidence, and warnings.

**Depends on:** ingestion article structure and source-span contracts.

**Acceptance:** malformed and incomplete entries remain representable; no
observation receives canonical citekey authority automatically.

### REF-GRAPH-02 — Numbered bibliography parser

Parse common numbered and author-year bibliography layouts from selected,
ordered source blocks.

**Depends on:** `REF-GRAPH-01`, `ING-STRUCTURE-01`.

**Acceptance:** entries crossing pages or columns retain ordered spans;
references embedded in prose are not mistaken for bibliography entries; parser
failure does not discard raw text.

### REF-GRAPH-03 — Direct-edge materializer

Convert reviewed bibliography observations into local candidate nodes and
source-located `cites` edges.

**Depends on:** `REF-GRAPH-02`.

**Acceptance:** reruns are idempotent; each edge identifies its parent entry;
removal or reordering in a new source blob does not rewrite historical evidence.

### REF-RECONCILE-01 — Candidate-to-reference reconciliation

Propose matches using normalized DOI, ISBN, arXiv ID, title, authors, year,
aliases, and existing bibliography occurrences.

**Depends on:** `REF-GRAPH-03`.

**Acceptance:** exact persistent-identifier conflicts fail; fuzzy matches remain
proposals; accepting a match is explicit; existing canonical keys are stable.

### REF-BACKWARD-01 — Bounded backward-citation queue

Create expansion jobs from selected direct citations with depth, breadth,
collection, and rights limits.

**Depends on:** `REF-RECONCILE-01`.

**Acceptance:** default depth is one; duplicate work is collapsed by accepted
identity; discovered nodes are not promoted or treated as evidence.

### REF-FORWARD-01 — Forward-citation discovery

Use provider adapters to discover works that cite an accepted source.

**Depends on:** `REF-METADATA-01`.

**Acceptance:** provider, query time, source URL, pagination, and incomplete
results are recorded; results enter the same candidate queue as backward
citations.

## Metadata and abstracts

### REF-METADATA-01 — Provider protocol and OpenAlex adapter

Generalize the existing Crossref client behind a provider protocol and add
OpenAlex metadata/citation discovery.

**Depends on:** current accepted reference model.

**Acceptance:** cache and rate-limit behavior are tested; fields retain provider
provenance; conflicting providers do not overwrite accepted metadata.

### REF-METADATA-02 — Metadata comparison report

Compare imported BibLaTeX fields with one or more provider observations and
produce field-level agreement, absence, and conflict records.

**Depends on:** `REF-METADATA-01`.

**Acceptance:** title normalization does not destroy original text; report
approval is separate from catalog mutation; source revision remains visible.

### REF-ABSTRACT-01 — Abstract persistence and import CLI

Persist provider-supplied abstracts as attached records and expose explicit
catalog import.

**Depends on:** `REF-METADATA-01`.

**Acceptance:** text, provider, source URL, retrieval time, language, checksum,
and status are required; provider absence creates no text; generated summaries
cannot be labeled source abstracts.

### REF-ABSTRACT-02 — Abstract screening record

Record inclusion, exclusion, or unresolved decisions against a review question.

**Depends on:** `REF-ABSTRACT-01`, `REF-REVIEW-01`.

**Acceptance:** decision, reviewer, date, rationale, and source abstract hash are
recorded; screening does not set `read` or `claim-support-checked`.

## Review state and evidence

### REF-REVIEW-01 — Review-state transition policy

Replace unrestricted status replacement with validated transitions and actor
provenance. See [the implemented owner-internal model](../review-state.md).

**Depends on:** accepted reference-authority architecture and `REF-IDENTITY-01`.

**Acceptance:** processors may record only orthogonal technical outcomes;
reading, claim-support checks, and collection inclusion require explicit human
actor authority, evidence, rationale, and exact supersession. Canonical identity
acceptance stays in `IdentityDecision`; scientific acceptance, manuscript use,
rights, and publication stay outside review state. Invalid, stale, and
concurrent transitions fail while corrected and superseded history remains
queryable.

### REF-EVIDENCE-01 — Claim-evidence record

Define a claim record linked to source citekey, exact source blob, page/section/
figure/table/equation locator, quoted or paraphrased support, disposition, and
human reviewer.

**Depends on:** `REF-REVIEW-01` and stable ingestion locators.

**Acceptance:** citation alone cannot satisfy the contract; unsupported,
contradictory, and contextual evidence are representable; application ownership
of the claim is explicit.

### REF-RIGHTS-01 — Rights and redistribution policy

Define source-asset and derivative rights statuses and validate tracked versus
private placement.

**Depends on:** current source-asset catalog.

**Acceptance:** unknown rights default to private; open-license claims include a
source; extracted figures and full transcriptions inherit or refine source
status; Git ignore is never represented as access control.

## Interchange and validation

### REF-EXPORT-01 — Deterministic catalog exports

Export accepted records, occurrences, aliases, assets, abstracts, candidates,
edges, and review state to versioned JSON and CSV; export publication-selected
records to BibLaTeX.

**Depends on:** schema-stable implementations above.

**Acceptance:** exports are deterministically ordered and contain no absolute
private paths; import/export round trips preserve identity and provenance.

### REF-GRAPH-EXPORT-01 — GraphML and JSON-LD views

Produce graph views without making a graph database authoritative.

**Depends on:** `REF-EXPORT-01`.

**Acceptance:** accepted and candidate nodes are distinguishable; edge locators
and verification status survive export; abstract text is optional.

### REF-VALIDATE-01 — Cross-artifact validator

Extend validation across BibLaTeX, SQLite, manifests, graph exports, notes,
PDFs, figures, and ingestion artifacts.

**Depends on:** `REF-RIGHTS-01`, `REF-EXPORT-01`.

**Acceptance:** citekey/basename violations, stale hashes, orphan edges,
malformed statuses, missing source provenance, and accidentally tracked private
assets fail with actionable diagnostics.
