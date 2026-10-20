# SearchReferenceAuthorityProjectionReadActionizer: schematics

```mermaid
flowchart LR
    Input[Typed input] --> Leaf[Strict owner codec and read leaf]
    Leaf --> Output[Immutable typed output]
```

The leaf remains path-free and imports from its exact defining module.

- [Overview](index.md)
