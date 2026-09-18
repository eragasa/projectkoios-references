# Reference object convention

## Canonical identity

An accepted reference exists only after replay of a valid actor-provenanced
promotion decision. BibLaTeX import, legacy seed mapping, normalization,
asset discovery, and filename similarity produce noncanonical candidates only.
See [Reference identity and authority](reference-identity.md).

For an accepted reference, its canonical BibLaTeX entry key is the portable
name shared by its reading note and locally held PDF:

```text
BibLaTeX key == Markdown basename == PDF basename
```

For example:

```text
@article{luttingerKohn1955, ...}
luttingerKohn1955.md
luttingerKohn1955.pdf
```

Directories are deployment concerns. A vault may place the two files in
separate configured directories while preserving their common basename.
Authorized roots are resolved and identity-bound before use. Root-relative
reads and writes reject traversal, non-normalized paths, symlink components,
and root replacement rather than following them.

## Key rules

Keys must start with an ASCII letter and contain only ASCII letters, numbers,
periods, underscores, or hyphens. They are limited to 200 characters, must not
end with a period, and must not equal a reserved portable filename such as
`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, or `LPT1`–`LPT9`. The shared
filesystem validator applies these rules before deriving a note, PDF, or output
path. Ingestion evidence is injected explicitly and is never found by deriving a
producer workspace path from a citekey.

Once accepted, a key is stable. A key change requires an explicit
actor-provenanced citekey-migration decision and a separately authorized
migration of the bibliography entry, note, source asset, and inbound citations.
The identity log preserves the former key as alias history; replaying the log
does not itself mutate any file or bibliography.

Multiple source artifacts use suffixes without changing the reference identity:

```text
marzari2012.pdf
marzari2012-supplement.pdf
marzari2012-accepted-manuscript.pdf
```

## Missing and private sources

A note may exist when no lawful full text has been located. Its source status
must say so; an unrelated file must never be substituted merely to satisfy the
filename convention.

PDFs are local source assets by default. They are not committed merely because
bibliographic metadata or a checksum manifest is tracked. Redistribution rights
must be reviewed separately. Git ignore rules are not access control.

## Evidence boundary

Matching a citation key, note, and PDF establishes identity and navigability. It
does not establish that:

- bibliographic metadata is correct;
- the PDF is complete or is the version of record;
- the work has been read;
- a cited passage supports a local claim; or
- a scientific conclusion has been accepted.

Those states must be represented and reviewed independently.
