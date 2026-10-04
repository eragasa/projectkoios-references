# SHA-256 PDF object store implementation

The adapter requires an explicit `AuthorizedRoot` and explicit byte cap at
construction. Receipt delegates to descriptor-confined anonymous staging,
incremental SHA-256 calculation, `%PDF-` prefix validation, optional declared
size validation, fsync, and no-replace publication as `<sha256>.pdf`.

A duplicate destination is not trusted blindly: its bytes, size, digest,
regular-file identity, filesystem, and mount boundary are reverified. The
owning result exposes no filesystem path.

```mermaid
flowchart LR
    S[Bounded binary stream] --> H[Hash and validate in anonymous inode]
    H --> P[Publish with no replacement]
    P --> V[Verify created or existing object]
    V --> R[Digest, byte size, disposition]
```

- [Module index](index.md)
- [Schematic](schematic.md)
