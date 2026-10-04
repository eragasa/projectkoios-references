# Document/reference implementation

Immutable data objects inherit the capability's nominal base and retain bounded
validation with their owning models. Narrow repository protocols separate
bibliography, collection, missing-PDF, receipt, and binding behavior. The SQLite
adapter satisfies these ports structurally while the migration remains schema
compatible.

Explicit browser binding always resolves
`explicit-reference-document-selection`; verified local import always resolves
`verified-local-evidence-import`. The basis participates in binding identity.
Exact retries are idempotent and different citekey, digest, or basis occupancy
fails closed.

Receipt precedes binding in composed intake. If custody succeeds and one-to-one
binding conflicts, the result is `received-unbound` and retains the
receipt result rather than representing the request as mutation-free.

```mermaid
flowchart TD
    U[Bounded PDF stream] --> R[Receive immutable SHA object]
    R --> O[Record receipt observation]
    O --> B{Owner-selected binding action}
    B -->|explicit browser selection| E[Explicit linkage basis]
    B -->|verified local import| V[Verified-import linkage basis]
    E --> A[Atomic one-to-one binding]
    V --> A
    A -->|exact replay| I[Already bound]
    A -->|new| N[Bound]
    A -->|conflict after receipt| C[Received unbound conflict]
```

No operation changes BibTeX, establishes publication rights, accepts scientific
claims, or admits content to Search.

- [Capability index](index.md)
- [Schematic](schematic.md)
