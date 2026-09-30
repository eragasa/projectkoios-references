# `projectkoios.references` package schematic

This diagram expands only the module migrated in the current vertical slice.
Untouched package modules remain opaque.

```mermaid
flowchart LR
    I[identity replay module] --> P[citation_identity_projection]
    P --> O[Citation-facing identity outcomes]
    B[Project Koios base taxonomy] --> P
    U[Other References modules] -. unmigrated architecture .-> I
```

`citation_identity_projection` reads immutable replay output and introduces no
new identity authority or persistence.

- [Package index](index.md)
- [Implementation](implementation.md)
