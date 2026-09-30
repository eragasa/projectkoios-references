# `projectkoios` namespace implementation

```mermaid
sequenceDiagram
    participant C as Python consumer
    participant N as projectkoios namespace
    participant R as projectkoios.references
    C->>N: resolve namespace search path
    C->>R: import owned package or module
    R-->>C: References-owned objects and actions
```

Namespace discovery is configured in [`pyproject.toml`](../../../pyproject.toml).
Importing the namespace grants no reference, citation, scientific, rights, or
publication authority.

- [Namespace index](index.md)
- [Schematic](schematic.md)
