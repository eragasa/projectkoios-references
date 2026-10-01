# Citation inventory implementation

```mermaid
flowchart LR
    O[Replay-valid target owner Result] --> A[Adapter]
    A --> C[Canonical citations base records]
    C --> D[Citation-document projection]
```

The canonical implementations live in `citations/base.py`; key resolution state
lives in `citations/statuses.py`, and target grammar and resource ceilings live
in the private contract module. Every record is frozen, slotted, statically
`final`, and accepted at composition boundaries only by exact runtime type.

The package has no dependency on `citation_document`. The latter consumes these
records and temporarily exposes deprecated identity-preserving attributes for
old imports. Deprecation access does not create a subclass, wrapper, duplicate
contract, or alternate identity payload.

The live adapter evidence and target-owner provenance remain documented by the
[citation-document implementation](../citation_document/implementation.md).

- [Module index](index.md)
- [Schematic](schematic.md)
- source base: [`citations/base.py`](../../../../../src/python/projectkoios/references/citations/base.py)
