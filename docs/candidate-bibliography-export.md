# Candidate-bibliography export

## Status and authority

`projectkoios.references.candidate-bibliography-export@0.1.0` is a pure,
in-memory projection for private drafting. Its only result status is
`proposed-noncanonical-private-drafting`.

The projection does not accept a citekey or reference identity, authorize
publication, establish rights or scientific support, bind a PDF, import a
record, mutate a database, or write an output file. Callers must keep source
selection and any later filesystem publication under their respective owners.

## Inputs

A `CandidateBibliographySourceDeclaration` explicitly binds one collection ID
to a nonempty tuple of exact `SourceBibliographyObservation` values. Every
observation in one declaration must identify the same source ID, asserted
revision, safe relative source path, bibliography SHA-256, and bibliography byte
size. Source entry indexes must be contiguous from zero, and observed citekeys
and observation identities must be unique.

The declaration validates that each verbatim entry's BibTeX header declares the
observation's exact citekey. It does not reparse or normalize metadata. Source
PDF filenames or bytes are not bibliography authority and are not inputs to the
contract.

A `CandidateBibliographyExportRequest` accepts 1--32 declarations with unique
collection and declaration identities. Declaration order has no effect on the
request identity or output.

## Deterministic projection

`CandidateBibliographyExporter`:

1. validates at most 10,000 total observations and 50,000,000 declared source
   bytes;
2. indexes exact UTF-8 `verbatim_entry` bytes by observed citekey;
3. rejects one citekey associated with different entry bytes;
4. emits one copy when multiple declared sources contain the same citekey and
   byte-identical entry;
5. orders entries lexically by case-sensitive citekey;
6. joins unmodified entry bytes with two LF bytes and appends one final LF; and
7. rejects output larger than 50,000,000 bytes.

The result replays the request during construction. It returns the exact output
bytes, ordered citekeys, collection/source/observation provenance, fixed
candidate-only status, byte count, SHA-256 digest, and a deterministic result
identity. A modified result cannot retain an earlier request or result identity.

## Private-source boundary

Tracked tests use only sanitized fixture bibliographies. Private source bytes,
private paths, and private rendered output must remain outside Git. The library
contract never discovers or opens a source path; filesystem-backed import is a
separate caller step that produces the exact observations supplied here.

## Validation

```bash
uv run python -m pytest -q tests/test__CandidateBibliographyExport.py
uv run ruff check src/python tests tools
uv run mypy src/python/projectkoios/references
```
