# `CourseReferenceQueueTransportActionizer`

## Responsibility

Load fresh owner state and serialize the complete safe queue.

## Boundary

`CourseReferenceQueueTransportActionizer` is owned by `projectkoios.references.courses.transport.queue` and follows the single-action `DataObjectActionizer` taxonomy. It carries no filesystem path, database location, source bytes, or mutable container.

## Collaboration

It collaborates only with the matching typed owner action and immutable transport values. API may route or serialize the result but need not traverse the private authority graph.

## Architecture views

- [Schematics](schematics.md)
- [Numerics](numerics.md)
- [Scientific authority](scientific.md)
- [Parent](../index.md)
