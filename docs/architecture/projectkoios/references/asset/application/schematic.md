# Asset-application schematic

```mermaid
classDiagram
    class DataObjectActionRequest
    class DataObjectActionResult
    class DataObjectActionizer
    class AssetApplicationOperationRequest
    class AssetApplicationOperationResult
    class AssetApplicationOperation
    class AssetApplicationError
    DataObjectActionRequest <|-- AssetApplicationOperationRequest
    DataObjectActionResult <|-- AssetApplicationOperationResult
    DataObjectActionizer <|-- AssetApplicationOperation
    AssetApplicationOperation --> AssetApplicationOperationRequest : consumes exact type
    AssetApplicationOperation --> AssetApplicationOperationResult : returns exact type
    AssetApplicationOperation --> AssetApplicationError : rejects selection conflicts
```

The owner operation is one indivisible transition binding. Internal authority
validation, catalog preflight and lock, filesystem publication, and catalog
recording are not exposed as reflectively inferred Workflow topology.
