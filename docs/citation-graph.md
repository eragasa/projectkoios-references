# Source-backed citation graph

## Authority boundary

A citation graph records only that an exact parent source contains a direct
bibliography entry. It does not establish review membership, relevance,
reading, claim support, canonical identity or citekey, scientific validity,
rights, manuscript use, or publication acceptance.

Every candidate is fixed to `unaccepted-candidate` and
`unaccepted-normalized-proposal`. Every edge is fixed to
`source-observed-only`. The only supported relation is direct `cites`.

## Identity model

`CitationSourceObservation` hashes:

- graph record schema and authority kind;
- logical source ID;
- asserted source revision, if supplied;
- safe relative source path;
- exact source SHA-256; and
- source byte size.

`CitationCandidate` hashes that source-observation ID and the exact entry
locator. Its source-verbatim entry, identifier, title, and authors are stored
separately from proposed citekey, type, title, ordered authors, year, and
normalized DOI. Changing a proposal at the same exact source/locator is a
conflict rather than a rewrite. Changing the source revision, source content,
or locator creates a new candidate identity.

`CitationEdge` hashes the source-observation ID, candidate target, direct
relation, and locator. Whole-graph validation requires both domains to exist
and requires the edge source/locator to equal its target candidate evidence.
A graph may be wholly empty; otherwise every supplied source and candidate must
participate in a direct edge. Source-only batches, duplicate rows, duplicate
source/locator slots, and duplicate edges fail before catalog mutation.

No supersession is inferred from a later source. New source revisions append
new observations, candidates, and edges while old evidence remains. A future
supersession relation must carry its own evidence and review before it can be
implemented.

## CSV import

`load_candidate_graph(sources, nodes, edges)` reads exactly three UTF-8 CSV
files before returning a `CitationGraph`. Headers are exact and ordered.
Precomputed IDs are required and recomputed from row evidence.

`sources.csv`:

```text
source_observation_id,source_id,asserted_source_revision,source_path,source_sha256,source_byte_size
```

`nodes.csv`:

```text
candidate_id,source_observation_id,source_locator,verbatim_entry,verbatim_identifier,verbatim_title,verbatim_authors,proposed_citekey,proposed_container_or_type,proposed_title,proposed_authors_json,proposed_year,proposed_doi
```

`edges.csv`:

```text
edge_id,source_observation_id,target_candidate_id,relation,source_locator
```

Empty optional verbatim fields mean unavailable evidence; they must not be
filled by inference. At least one verbatim entry, identifier, title, or author
field is required. `proposed_authors_json` is always a JSON array. A proposed
DOI must already be normalized; its original source form belongs in
`verbatim_identifier`.

Default hard import ceilings are:

| Dimension | Ceiling |
|---|---:|
| Each CSV file | 2,000,000 bytes |
| Three files total | 4,000,000 bytes |
| Source rows | 128 |
| Candidate rows | 10,000 |
| Edge rows | 10,000 |
| Direct edges per source | 2,000 |
| Ordinary field | 4,096 UTF-8 bytes |
| Verbatim entry | 262,144 UTF-8 bytes |
| Proposed authors per candidate | 256 |

`GraphImportLimits` can tighten but cannot raise these ceilings. The CLI
finishes CSV parsing and whole-graph validation before opening or initializing
a catalog, so invalid input cannot create an otherwise absent catalog.
`ReferenceCatalog.import_citation_graph()` then inserts all sources, candidates,
and edges in one immediate transaction. Exact replay is idempotent; any
conflict or late integrity failure rolls the entire batch back. Catalog reads
revalidate canonical JSON, scalar agreement, foreign keys, graph domains, and
global hard limits.
