# `projectkoios.references` package schematic

This diagram expands only the modules migrated in the current vertical slices.
Untouched package modules remain opaque.

```mermaid
flowchart LR
    I[identity replay module] --> P[citation_identity]
    P --> O[Citation-facing identity outcomes]
    T[Neutral target citation snapshot] --> C[citations]
    O2[Bibliography observation] --> G[bibliography]
    C --> G
    C --> D[citation_document]
    G --> D
    P --> D
    E[Document observations and neutral links] --> D
    D --> R[Citation document projection]
    B[Project Koios base taxonomy] --> P
    B --> D
    U[Other References modules] -. unmigrated architecture .-> I
```

`citation_identity` reads immutable replay output. `citations` and
`bibliography` preserve target and evidence ownership; `citation_document`
composes those records with document evidence. None of these modules
introduces identity promotion, rights, review, use, or ingestion authority.

- [Package index](index.md)
- [Implementation](implementation.md)
