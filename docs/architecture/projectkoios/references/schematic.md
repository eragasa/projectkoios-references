# `projectkoios.references` package schematic

This diagram expands only the modules migrated in the current vertical slices.
Untouched package modules remain opaque.

```mermaid
flowchart LR
    I[identity replay module] --> P[citation.identity]
    P --> O[Citation-facing identity outcomes]
    T[Neutral target citation snapshot] --> C[citations]
    O2[Bibliography observation] --> B[bibliography]
    C --> B
    C --> X[Consumer target association]
    B --> X
    K[Project Koios base taxonomy] --> P
    U[Other References modules] -. unmigrated architecture .-> I
```

`citation.identity` reads immutable replay output. `citations` preserves exact
target-owned records, while `bibliography` binds an exact target bibliography
entry to exact References evidence. Neither package owns citation-document
processing, receipts, availability, rights, review, use, or ingestion authority.

- [Package index](index.md)
- [Implementation](implementation.md)
