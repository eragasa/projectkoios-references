# Bounded reference I/O

Reference-facing commands use explicit, immutable I/O profiles. The profiles
are denial-of-service boundaries, not claims that a search was exhaustive.
Callers may tighten a profile, but `ReferenceIOLimits` rejects values above the
repository hard ceilings.

A successful evidence-producing operation records its effective profile and
content-derived profile identity. A limit failure raises
`ReferenceIOLimitError` (or the graph/provider-specific subtype) with:

- `code`;
- the resource and exceeded dimension;
- the configured and observed values;
- `coverage_status = "incomplete"`;
- the complete effective profile and its identity.

Limit failure never means that a reference, PDF, citation, provider record, or
other candidate is absent. Commands validate bounded inputs before catalog or
output publication, and do not publish partial evidence.

## Default profiles

| Operation | Files | Per file | Total observed bytes | Rows/items | Other bounds |
| --- | ---: | ---: | ---: | ---: | --- |
| BibLaTeX import | 1 | 50 MB | 50 MB | 10,000 entries | 1 MB verbatim entry; nesting 128 |
| asset discovery/materialization | 10,000 | 4 GB | 40 GB | 20,000 reference inputs; 100,000 matches | 100,000 indexed match evaluations; directory entries and JSON plans bounded |
| acquisition create/verify | 256 | 4 GB | 40 GB | 256 CSV rows | CSV/JSON 1 MB; JSON depth 64 |
| collection reconciliation | 10,000 | 4 GB | 40 GB | 10,000 CSV rows | CSV 50 MB; JSON 20 MB/depth 64; TeX 50 MB |
| reconciliation package verification | 100,000 | 50 MB | 100 MB | 100,000 entries | manifest 20 MB; JSON depth 64 |
| reference validation | 20,000 | 1 MB note | 50 MB notes | 10,000 candidates | directory entries bounded |
| metadata provider/cache | 1,000 cache files | 2 MB response / 3 MB cache | 500 MB per-request cache replay | 2,000 directory entries | JSON depth 64; provider field bounds |
| citation graph import | 3 CSV files | 2 MB | 4 MB | 128 sources; 10,000 candidates and edges | 2,000 direct edges per source; JSON depth 64 |

The exact machine-readable values are in `io_limits.py` and
`GraphImportLimits`; generated evidence records those values rather than
relying on this explanatory table.

## Streaming and allocation behavior

PDF and arbitrary asset hashing uses a single descriptor-confined streaming
observation. It records SHA-256, byte size, and only the prefix required for
format checking. Asset discovery hashes each matched file once even when the
file produces multiple candidate associations. Materialization streams into a
same-directory temporary file, verifies the planned digest and size, fsyncs,
and atomically publishes without loading the PDF into memory.

Directory walks cap entries before sorting, cap matching files, reject
symlinks, and limit recursion depth. CSV readers stop on the first row beyond
the active limit. JSON and BibLaTeX nesting are checked before parser
allocation; arrays, text fields, candidates, and graph breadth are checked
before durable mutation.

Python exposes its CSV parser's field ceiling only as process-global state.
Repository readers serialize changes under a lock and restore the prior value;
current commands parse CSV synchronously. Concurrent embedding alongside
unrelated CSV readers in the same process is not supported. Revisit a
per-reader parser before adding that mode under the broader API/compatibility
work in issue #26.

Normal inputs remain deterministic: tightening a limit without excluding any
input does not change candidate identities, graph identities, or normalized
content. Effective-limit evidence intentionally changes the enclosing plan,
manifest, provider observation, CLI report, or reconciliation package identity
when the active profile changes.

## Authority boundary

Passing bounded-I/O checks proves only that the named bytes were processed
within the recorded resource envelope. It does not establish canonical
identity, citation relevance, complete search coverage, rights, scientific
validity, independent revalidation, publication readiness, or contract
acceptance.
