# Deprecated citation-document namespace implementation

```mermaid
flowchart LR
    O[citation_document import] --> W[Deprecation warning]
    W --> D[documents exact object]
    W --> C[citations exact object]
    W --> B[bibliography exact object]
```

The compatibility package defines no domain class and constructs no wrapper.
Its facade forwards attributes to their canonical owner and warns at most once
per name. Old submodules import canonical objects directly and warn when the
submodule is imported. Identity tests require `old is new`.

- [Module index](index.md)
- [Schematic](schematic.md)
- canonical [documents implementation](../documents/implementation.md)
