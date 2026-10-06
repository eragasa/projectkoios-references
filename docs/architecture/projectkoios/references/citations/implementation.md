# Citation inventory implementation

```mermaid
flowchart LR
    O[Replay-valid target owner Result] --> A[Adapter]
    A --> C[Canonical citations base records]
    C --> D[Citation-document projection]
```

The canonical implementations live in `citations/base.py`; key resolution state
lives in `citations/statuses.py`, and target grammar and resource ceilings live
in the private contract module. `citations/resolution.py` applies accepted
canonical-name and alias precedence, bounded identity projection, and fail-closed
resolved/ambiguous/unresolved reduction over neutral candidate mappings. Every
record is frozen, slotted, statically
`final`, and accepted at composition boundaries only by exact runtime type.

The package has no dependency on `citation.document`. The latter consumes these
records through direct owner-module imports and exposes no compatibility facade,
wrapper, duplicate contract, or alternate identity payload.

The live adapter evidence and target-owner provenance remain documented by the
[citation-document implementation](../citation/document/implementation.md).

- [Module index](index.md)
- [Schematic](schematic.md)
- source base: [`citations/base.py`](../../../../../src/python/projectkoios/references/citations/base.py)
- resolution: [`citations/resolution.py`](../../../../../src/python/projectkoios/references/citations/resolution.py)
