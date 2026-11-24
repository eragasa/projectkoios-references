from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import final

from projectkoios.base import DataObjectActionRequest
from projectkoios.references.assets import SearchRoot
from projectkoios.references.path_safety import (
    RootStorageClass,
    validate_citekey,
    validate_relative_path,
)

from .error import AssetApplicationError


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssetApplicationOperationRequest(DataObjectActionRequest):
    """Bind exact capabilities and selectors for one authorized application."""

    plan: Path
    plan_storage_class: RootStorageClass
    authorization: Path
    authorization_storage_class: RootStorageClass
    identity_projection: Path
    identity_projection_storage_class: RootStorageClass
    citekey: str
    candidate_path: str | None
    search_roots: tuple[SearchRoot, ...]
    destination: Path
    destination_storage_class: RootStorageClass
    rights_status: str
    catalog: Path | None = None
    catalog_storage_class: RootStorageClass | None = None

    def __post_init__(self) -> None:
        for field_name, path_value in (
            ("plan", self.plan),
            ("authorization", self.authorization),
            ("identity_projection", self.identity_projection),
            ("destination", self.destination),
        ):
            if not isinstance(path_value, Path):
                raise TypeError(f"{field_name} must be a Path")
        for field_name, storage_value in (
            ("plan_storage_class", self.plan_storage_class),
            (
                "authorization_storage_class",
                self.authorization_storage_class,
            ),
            (
                "identity_projection_storage_class",
                self.identity_projection_storage_class,
            ),
            ("destination_storage_class", self.destination_storage_class),
        ):
            if not isinstance(storage_value, RootStorageClass):
                raise TypeError(f"{field_name} must be explicit")
        validate_citekey(self.citekey, field="selected proposed citekey")
        if self.candidate_path is not None:
            validate_relative_path(self.candidate_path)
        if (
            not isinstance(self.search_roots, tuple)
            or not self.search_roots
            or any(type(item) is not SearchRoot for item in self.search_roots)
        ):
            raise TypeError("search_roots must be a non-empty SearchRoot tuple")
        aliases = tuple(item.alias for item in self.search_roots)
        if len(aliases) != len(set(aliases)):
            raise AssetApplicationError("search-root aliases must be unique")
        if (
            not isinstance(self.rights_status, str)
            or not self.rights_status
            or len(self.rights_status) > 4_096
        ):
            raise ValueError("rights_status must be a bounded non-empty string")
        if (self.catalog is None) != (self.catalog_storage_class is None):
            raise AssetApplicationError(
                "catalog path and storage class must be supplied together"
            )
        if self.catalog is not None and not isinstance(self.catalog, Path):
            raise TypeError("catalog must be a Path when supplied")
        if self.catalog_storage_class is not None and not isinstance(
            self.catalog_storage_class, RootStorageClass
        ):
            raise TypeError("catalog_storage_class must be explicit")
