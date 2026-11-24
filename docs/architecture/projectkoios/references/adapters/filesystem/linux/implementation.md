# `projectkoios.references.adapters.filesystem.linux` implementation

OS-specific filesystem behavior is isolated behind this adapter.

```mermaid
flowchart LR
  Domain --> Adapter["projectkoios.references.adapters.filesystem.linux"]
  Adapter --> OS
```

[Back to package](index.md)
