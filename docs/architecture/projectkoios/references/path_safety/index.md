# `projectkoios.references.path_safety`

This package owns portable locator validation, storage preflight, descriptor-confined filesystem access, bounded observation, deterministic inventory, and atomic local publication. The historical import path remains available through a small explicit package facade.

## Classes

- [`AuthorizedRoot`](AuthorizedRoot/index.md)
- [`AuthorizedRootIdentity`](AuthorizedRootIdentity/index.md)
- [`AuthorizedRootObservation`](AuthorizedRootObservation/index.md)
- [`AuthorizedRootPublication`](AuthorizedRootPublication/index.md)
- [`AuthorizedRootScanning`](AuthorizedRootScanning/index.md)
- [`AddressedFilePublication`](AddressedFilePublication/index.md)
- [`CloudPlaceholderProbe`](CloudPlaceholderProbe/index.md)
- [`CloudRootMutationError`](CloudRootMutationError/index.md)
- [`DescriptorFilesystem`](DescriptorFilesystem/index.md)
- [`FileObservation`](FileObservation/index.md)
- [`FilesystemBoundaryError`](FilesystemBoundaryError/index.md)
- [`FilesystemInventory`](FilesystemInventory/index.md)
- [`FilesystemInventoryIssue`](FilesystemInventoryIssue/index.md)
- [`FilesystemIssueKind`](FilesystemIssueKind/index.md)
- [`MacOSFileProviderPlaceholderProbe`](MacOSFileProviderPlaceholderProbe/index.md)
- [`PathLimitError`](PathLimitError/index.md)
- [`PathSafetyError`](PathSafetyError/index.md)
- [`PlaceholderObservation`](PlaceholderObservation/index.md)
- [`PlaceholderPreflightError`](PlaceholderPreflightError/index.md)
- [`PlaceholderProbeIdentity`](PlaceholderProbeIdentity/index.md)
- [`PlaceholderProbeSupport`](PlaceholderProbeSupport/index.md)
- [`PlaceholderStatus`](PlaceholderStatus/index.md)
- [`PortablePathValidator`](PortablePathValidator/index.md)
- [`RootPreflightEvidence`](RootPreflightEvidence/index.md)
- [`RootStorageClass`](RootStorageClass/index.md)
- [`UnsupportedCloudPlaceholderProbe`](UnsupportedCloudPlaceholderProbe/index.md)

## Security boundary

Cloud-backed roots are metadata-only unless a future explicit hydration authority is introduced. Local operations reject symlinks and device or mount crossings, bind open descriptors to stable root identities, and apply hard byte, file, entry, and depth bounds. Directory claims use platform atomic no-replace rename. Destructive exact rollback is disabled because portable conditional unlink cannot bind deletion to a previously verified inode. Local hard-linked bytes remain inside the trusted local-root content boundary and are not treated as independently owned copies.

Safe path observation grants no rights, use, ingestion, review, Search, scientific, or publication authority.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source: [`path_safety`](../../../../../src/python/projectkoios/references/path_safety/)
- focused tests: [`tests/package/projectkoios/references/path_safety`](../../../../../tests/package/projectkoios/references/path_safety/)
- [Package index](../index.md)
