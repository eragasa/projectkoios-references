# Catalog schematic

```mermaid
classDiagram
    class CatalogError
    class CatalogSchemaError
    class CatalogMigrationRequired
    class CatalogConflictError
    class CandidateConflictError
    class CatalogSchemaInfo {
        +int schema_version
        +str schema_fingerprint
        +str authority_boundary
    }
    class CatalogMigrationPlan {
        +int source_schema_version
        +str source_schema_fingerprint
        +str source_kind
        +int target_schema_version
        +str target_schema_fingerprint
        +bool backup_required
        +str authority_effect
    }
    class ReferenceCatalog {
        +Path path
        +initialize()
        +schema_info()
        +migration_plan()
        +migrate()
        +import_candidates()
        +record_source_asset()
        +record_source_assets()
        +import_review_records()
        +import_state_projections()
        +import_citation_graph()
        +counts()
    }
    CatalogError <|-- CatalogSchemaError
    CatalogSchemaError <|-- CatalogMigrationRequired
    CatalogError <|-- CatalogConflictError
    CatalogConflictError <|-- CandidateConflictError
    ReferenceCatalog ..> CatalogSchemaInfo : reports
    ReferenceCatalog ..> CatalogMigrationPlan : plans
    ReferenceCatalog ..> CatalogMigrationRequired : raises
    ReferenceCatalog ..> CatalogConflictError : raises
```

Private implementation bases separate persisted-row replay from schema,
migration, and authorized-path mechanics. They add no public catalog facade and
no alternate authority model.

- [Module index](index.md)
- [Implementation](implementation.md)
