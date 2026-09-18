# Padberg--Hoffmann citation-graph seed

This public graph contains the 34 direct bibliography observations transcribed
from `padbergHoffmann2015`.

- `sources.csv` binds the graph to the exact parent PDF digest, byte size,
  asserted content revision, and relative asset locator recorded by the public
  manifest.
- `nodes.csv` gives every entry a content identity derived from that parent
  source observation and its source locator. Existing title and author
  transcriptions are retained in source-verbatim fields. DOI, citekey, type,
  title, author, and year normalizations remain separate unaccepted proposals.
- `edges.csv` gives every direct `cites` observation its own content identity
  and repeats the exact source observation, candidate target, and entry locator.

The earlier pilot did not retain complete verbatim bibliography-entry text or
source-verbatim identifiers, so those fields remain empty rather than being
invented. Existing title and author transcriptions are preserved exactly, but
were not rechecked against a private source asset during this public migration.
The graph loader rejects missing domains, conflicting/duplicate rows, changed
identities, malformed or oversized CSV, and excessive graph breadth.

Graph membership records only that the exact parent source contains a direct
bibliography entry. It does not recursively import candidate bibliographies and
does not imply relevance, reading, claim support, canonical acceptance,
scientific validity, or publication use. Source revision/content changes create
new evidence and retain old evidence; no supersession is inferred.
