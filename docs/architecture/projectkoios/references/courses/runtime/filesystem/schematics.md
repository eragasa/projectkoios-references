# courses.runtime.filesystem: schematics

```mermaid
flowchart LR
    Config[Owner runtime configuration] --> Filesystem[Descriptor-confined filesystem adapters]
    Evidence[(Bibliography, asset, and linkage bytes)] --> Filesystem
    Projection[(Persisted Search authority bytes)] --> Filesystem
    Filesystem --> Safe[Path-free immutable results]
```

Runtime paths, root aliases, storage classes, and placeholder probes remain constructor-injected capabilities. They never enter core requests, results, or content identities.

- [Overview](index.md)
