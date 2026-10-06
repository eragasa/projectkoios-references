# `projectkoios.references.asset_application`

Runtime-neutral References-owned operation for applying one explicitly
authorized asset under its canonical filename, optionally coupled to the
schema-5 working catalog transaction.

- [`AssetApplicationOperationRequest`](AssetApplicationOperationRequest/index.md)
- [`AssetApplicationOperationResult`](AssetApplicationOperationResult/index.md)
- [`AssetApplicationOperation`](AssetApplicationOperation/index.md)
- [`AssetApplicationError`](AssetApplicationError/index.md)

The stable action identity is
`projectkoios.references.asset_application.operation@1`. An external Workflow
CPN transition may bind that identity explicitly and use the request/result as
token colors. References retains authority validation, source and destination
preflight, no-replace publication, catalog conflict checks, and transaction
semantics. No scheduler, marking, retry, approval, or transition-occurrence
state is defined here.

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [`projectkoios.references`](../index.md)
