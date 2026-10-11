"""Filesystem runtime configuration and capability declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from projectkoios.base import DataObjectModel
from projectkoios.references.courses.authority.evidence import (
    ReferenceRecordDiscrepancy,
)
from projectkoios.references.path_safety import (
    CloudPlaceholderProbe,
    RootStorageClass,
)

_MAX_SOURCES = 64


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityBibliographySource(DataObjectModel):
    """Configure one explicit owner-private bibliography source."""

    collection_id: str
    bibliography_path: Path = field(repr=False)
    source_id: str
    asserted_source_revision: str | None
    source_path: str
    storage_class: RootStorageClass

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.collection_id) is not str or not self.collection_id:
            raise ValueError("collection_id must be nonempty")
        if not isinstance(self.bibliography_path, Path):
            raise TypeError("bibliography_path must be a Path")
        if type(self.source_id) is not str or not self.source_id:
            raise ValueError("source_id must be nonempty")
        if self.asserted_source_revision is not None and (
            type(self.asserted_source_revision) is not str
            or not self.asserted_source_revision
        ):
            raise ValueError("asserted_source_revision must be nonempty")
        if type(self.source_path) is not str or not self.source_path:
            raise ValueError("source_path must be nonempty")
        if not isinstance(self.storage_class, RootStorageClass):
            raise TypeError("storage_class must be RootStorageClass")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityAssetRoot(DataObjectModel):
    """Configure one runtime-only root used to reobserve catalog assets."""

    root_alias: str
    root_path: Path = field(repr=False)
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.root_alias) is not str or not self.root_alias:
            raise ValueError("root_alias must be nonempty")
        if not isinstance(self.root_path, Path):
            raise TypeError("root_path must be a Path")
        if not isinstance(self.storage_class, RootStorageClass):
            raise TypeError("storage_class must be RootStorageClass")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityRuntimeConfiguration(DataObjectModel):
    """Configure a concrete References-owned service without parsing in API."""

    course_id: str
    catalog_path: Path = field(repr=False)
    catalog_storage_class: RootStorageClass
    bibliography_sources: tuple[CourseReferenceAuthorityBibliographySource, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...] = ()
    asset_roots: tuple[CourseReferenceAuthorityAssetRoot, ...] = ()
    asset_linkage_path: Path | None = field(default=None, repr=False)
    asset_linkage_storage_class: RootStorageClass = RootStorageClass.LOCAL
    asset_linkage_placeholder_probe: CloudPlaceholderProbe | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.course_id) is not str or not self.course_id:
            raise ValueError("course_id must be nonempty")
        if not isinstance(self.catalog_path, Path):
            raise TypeError("catalog_path must be a Path")
        if not isinstance(self.catalog_storage_class, RootStorageClass):
            raise TypeError("catalog_storage_class must be RootStorageClass")
        if type(self.bibliography_sources) is not tuple or any(
            type(item) is not CourseReferenceAuthorityBibliographySource
            for item in self.bibliography_sources
        ):
            raise TypeError("bibliography_sources must be an exact typed tuple")
        if not self.bibliography_sources:
            raise ValueError("bibliography_sources must not be empty")
        if len(self.bibliography_sources) > _MAX_SOURCES:
            raise ValueError("bibliography source limit exceeded")
        if len({item.collection_id for item in self.bibliography_sources}) != (
            len(self.bibliography_sources)
        ):
            raise ValueError("bibliography collection identities repeat")
        if type(self.record_discrepancies) is not tuple or any(
            type(item) is not ReferenceRecordDiscrepancy
            for item in self.record_discrepancies
        ):
            raise TypeError("record_discrepancies must be an exact typed tuple")
        if type(self.asset_roots) is not tuple or any(
            type(item) is not CourseReferenceAuthorityAssetRoot
            for item in self.asset_roots
        ):
            raise TypeError("asset_roots must be an exact typed tuple")
        if len({item.root_alias for item in self.asset_roots}) != len(
            self.asset_roots
        ):
            raise ValueError("asset root aliases repeat")
        if self.asset_linkage_path is not None and not isinstance(
            self.asset_linkage_path,
            Path,
        ):
            raise TypeError("asset_linkage_path must be a Path")
        if not isinstance(
            self.asset_linkage_storage_class,
            RootStorageClass,
        ):
            raise TypeError(
                "asset_linkage_storage_class must be RootStorageClass"
            )
