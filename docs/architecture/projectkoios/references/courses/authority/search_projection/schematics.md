# courses.authority.search_projection: schematics

```mermaid
flowchart LR
    Evidence[(Replay-current owner evidence)] --> Producer[Projection actionizer]
    Producer --> Projection[SearchReferenceAuthorityProjection]
    Request[Path-free expected identities] --> Reader[Strict read actionizer]
    Source[Read-only bytes source port] --> Reader
    Reader --> Loaded[Correlated exact typed projection]
```

The producer emits the defining type. The read leaf verifies expected byte facts before strict canonical decoding and constructor-based identity reconstruction. It has no filesystem or catalog dependency.

- [Overview](index.md)
