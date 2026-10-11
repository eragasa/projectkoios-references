# `CanonicalAssetPutTransportRequest`

## Responsibility

Carry one HTTP-safe idempotent asset PUT plus trusted scope.

## Boundary

`CanonicalAssetPutTransportRequest` is owned by `projectkoios.references.courses.transport.asset` and follows the immutable `DataObjectActionRequest` taxonomy. It carries no filesystem path, database location, source bytes, or mutable container.

## Collaboration

It collaborates only with the matching typed owner action and immutable transport values. API may route or serialize the result but need not traverse the private authority graph.

## Architecture views

- [Schematics](schematics.md)
- [Numerics](numerics.md)
- [Scientific authority](scientific.md)
- [Parent](../index.md)
