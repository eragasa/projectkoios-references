# Document/reference schematic

```mermaid
flowchart LR
    M[Bibliography metadata] --> C[Collection requirements]
    P[SHA-addressed PDF] --> R[Receipt]
    C --> B[Optional one-to-one binding]
    R --> B
    B --> D[Derived missing-PDF list]
    R --> I[Composed intake outcome]
    B --> I
```

Bindings connect independent document and reference identities. Missing status
is derived and is never persisted as workflow state.

- [Capability index](index.md)
- [Implementation](implementation.md)
