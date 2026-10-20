# SearchReferenceAuthorityProjectionReadError: schematics

```mermaid
flowchart LR
    Failure[Filesystem or preflight failure] --> Boundary[Runtime translation boundary]
    Boundary --> Error[Deterministic path-free owner error]
```

The original failure and its path-bearing cause/context graph do not cross the adapter boundary.

- [Overview](index.md)
