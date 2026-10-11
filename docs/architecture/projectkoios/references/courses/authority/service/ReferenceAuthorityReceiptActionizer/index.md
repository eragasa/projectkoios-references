# `ReferenceAuthorityReceiptActionizer`

## Responsibility

Reread owner state and verify one exact post-append receipt.

## Boundary

`ReferenceAuthorityReceiptActionizer` is owned by `projectkoios.references.courses.authority.service`. It does not grant scientific, publication, rights, or cross-owner authority beyond its typed contract.

## Collaboration

The contract collaborates only through immutable typed values and the `DataObjectActionizer[ReferenceAuthorityReceiptRequest, ReferenceAuthorityReceiptResult]` taxonomy boundary. Private filesystem paths, catalog locations, and protected payload bytes are excluded from public results.

## Architecture views

- [Schematics](schematics.md)
- [Numerics](numerics.md)
- [Scientific authority](scientific.md)
- [Parent](../index.md)
