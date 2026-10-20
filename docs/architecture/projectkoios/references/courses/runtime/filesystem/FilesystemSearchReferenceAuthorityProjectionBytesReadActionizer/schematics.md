# FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer: schematics

```mermaid
flowchart LR
    Config[Path, root, storage, probe] --> Adapter[Descriptor-confined bounded read]
    Request[Path-free read request] --> Adapter
    Adapter --> Result[Path-free bytes result]
    Adapter -->|read failure| Error[Path-free owner read error]
```

The adapter is read-only and supplies no decoding or authority interpretation. Path-safety and operating-system read failures are translated outside their active exception context, so the original path-bearing exception graph is not retained.

- [Overview](index.md)
