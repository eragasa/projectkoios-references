# `projectkoios.references` package implementation

The documented path is deliberately one-way: identity replay establishes
bounded reference identity state, the identity projector exposes safe outcomes,
canonical citation and bibliography packages preserve exact target evidence,
and citation-document control composes those records with identity and document
evidence without changing owner authority.

```mermaid
sequenceDiagram
    participant T as Target snapshot owner
    participant R as Identity replay
    participant Q as Citations + bibliography
    participant I as CitationIdentityProjector
    participant D as CitationDocumentProjector
    participant L as CitationSourceDocumentLinker
    participant C as Consumer
    T-->>Q: complete neutral target snapshot
    Q-->>D: canonical inventory + bindings
    R-->>I: immutable IdentityProjection
    D->>I: canonical batches of exact identity IDs
    I-->>D: identity projection items
    D-->>C: citation document projection
    C->>L: resolved item + available descriptor + pre-effect intent
    L-->>C: neutral source-document link
    C->>D: exact link + same owner inputs
    D-->>C: rebuilt available-linked projection
    Note over D,C: no rights, use, review, ingestion, or publication claim
```

The References root initializer is unchanged by these slices. Consumers import
citation inventory and bibliography binding from their canonical focused
package facades, identity from its owner, and document control from
`citation_document`. Moved names on the latter are bounded deprecated
identity-preserving attributes; there is no root-facade expansion or duplicate
implementation.

Evidence:

- package source: [`src/python/projectkoios/references`](../../../../src/python/projectkoios/references)
- identity tests: [`test__CitationIdentityProjection.py`](../../../../tests/test__CitationIdentityProjection.py)
- citation document tests: [`test__CitationDocumentProjection.py`](../../../../tests/test__CitationDocumentProjection.py)

- [Package index](index.md)
- [Schematic](schematic.md)
