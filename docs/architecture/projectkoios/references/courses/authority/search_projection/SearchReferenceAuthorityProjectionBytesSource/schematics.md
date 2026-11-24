# SearchReferenceAuthorityProjectionBytesSource: schematics

```mermaid
flowchart LR
    Input[Typed input] --> Leaf[Read-only bytes source port]
    Leaf --> Output[Immutable typed output]
```

The leaf remains path-free and imports from its exact defining module.

- [Overview](index.md)
