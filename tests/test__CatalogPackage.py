from __future__ import annotations

import pickle

from projectkoios.references import ReferenceCatalog as RootReferenceCatalog
from projectkoios.references.catalog import (
    CandidateConflictError,
    CatalogConflictError,
    CatalogError,
    CatalogMigrationPlan,
    CatalogMigrationRequired,
    CatalogSchemaError,
    CatalogSchemaInfo,
    ReferenceCatalog,
    schema,
)


def test__catalog_package__preserves_public_facade_identity() -> None:
    assert RootReferenceCatalog is ReferenceCatalog
    assert CatalogError is schema.CatalogError
    assert CatalogSchemaError is schema.CatalogSchemaError
    assert CatalogMigrationRequired is schema.CatalogMigrationRequired
    assert CatalogConflictError is schema.CatalogConflictError
    assert CandidateConflictError is schema.CandidateConflictError
    assert CatalogSchemaInfo is schema.CatalogSchemaInfo
    assert CatalogMigrationPlan is schema.CatalogMigrationPlan


def test__catalog_package__preserves_public_pickle_module() -> None:
    public_types = (
        CatalogError,
        CatalogSchemaError,
        CatalogMigrationRequired,
        CatalogConflictError,
        CandidateConflictError,
        CatalogSchemaInfo,
        CatalogMigrationPlan,
        ReferenceCatalog,
    )
    assert all(
        public_type.__module__ == "projectkoios.references.catalog"
        for public_type in public_types
    )
    schema_info = CatalogSchemaInfo(5, "catalog-schema:sha256:synthetic")
    assert pickle.loads(pickle.dumps(schema_info)) == schema_info
