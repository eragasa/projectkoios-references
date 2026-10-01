# Path-safety schematic

```mermaid
classDiagram
    class AuthorizedRootIdentity
    class AuthorizedRootObservation
    class AuthorizedRootScanning
    class AuthorizedRootPublication
    class AuthorizedRoot
    class DescriptorFilesystem
    class RootPreflightEvidence
    class PlaceholderObservation
    class FilesystemInventory
    class CloudPlaceholderProbe
    AuthorizedRootIdentity <|-- AuthorizedRootObservation
    AuthorizedRootIdentity <|-- AuthorizedRootScanning
    AuthorizedRootIdentity <|-- AuthorizedRootPublication
    AuthorizedRootObservation <|-- AuthorizedRoot
    AuthorizedRootScanning <|-- AuthorizedRoot
    AuthorizedRootPublication <|-- AuthorizedRoot
    AuthorizedRoot ..> DescriptorFilesystem : descriptor mechanics
    AuthorizedRootIdentity --> RootPreflightEvidence : binds
    AuthorizedRootObservation --> PlaceholderObservation : reports
    AuthorizedRootScanning --> FilesystemInventory : reports
    AuthorizedRootObservation ..> CloudPlaceholderProbe : metadata only
```

The composed root remains the supported filesystem capability. Focused base classes express implementation ownership; they are not alternate authority grants or public workflow entry points.

- [Module index](index.md)
- [Implementation](implementation.md)
