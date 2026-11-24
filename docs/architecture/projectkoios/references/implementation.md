# `projectkoios.references` package implementation

The documented citation path preserves two independent owner boundaries:
complete neutral target citation inventory and exact bibliography observation
binding. Identity replay remains a separate References capability and does not
gate document processing.

```mermaid
sequenceDiagram
    participant T as Target snapshot owner
    participant C as Citations
    participant O as Bibliography observation
    participant B as Bibliography binding
    participant X as Consumer
    T-->>C: complete neutral target snapshot
    C-->>X: exact target records and identities
    C-->>B: exact target bibliography entry
    O-->>B: replay-valid source observation
    B-->>X: exact entry-observation binding
    Note over C,X: no document availability, processing, or receipt state
```

The References root initializer is unchanged by these slices. Consumers import
citation inventory and bibliography bindings from their canonical focused
package facades. References defines no citation-document projection,
availability, processing, receipt, or target-association DTO in this slice.

Evidence:

- package source: [`src/python/projectkoios/references`](../../../../src/python/projectkoios/references)
- target adapter tests: [`test__CitationDocumentTargetAdapter.py`](../../../../tests/test__CitationDocumentTargetAdapter.py)

- [Package index](index.md)
- [Schematic](schematic.md)
