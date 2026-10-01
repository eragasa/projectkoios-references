# `projectkoios.references` package schematic

This diagram expands only the modules migrated in the current vertical slices.
Untouched package modules remain opaque.

```mermaid
flowchart LR
    I[identity replay module] --> P[citation_identity]
    P --> O[Citation-facing identity outcomes]
    T[Neutral target citation snapshot] --> D[citation_document]
    P --> D
    E[Document observations and neutral links] --> D
    D --> R[Citation document projection]
    B[Project Koios base taxonomy] --> P
    B --> D
    U[Other References modules] -. unmigrated architecture .-> I
```

`citation_identity` reads immutable replay output. `citation_document` composes
that output with owner-supplied target and document evidence. Neither module
introduces identity promotion, rights, review, use, or ingestion authority.

- [Package index](index.md)
- [Implementation](implementation.md)
