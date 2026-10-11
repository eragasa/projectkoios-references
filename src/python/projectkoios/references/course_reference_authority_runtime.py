"""Filesystem-backed runtime composition for course reference authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyExportRequest,
    CandidateBibliographyRenderer,
    CandidateBibliographyRenderRequest,
    CandidateBibliographySourceDeclaration,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.course_reference_authority import (
    CourseReferenceAuthorityError,
    CourseReferenceAuthorityOwnerEvidence,
    CourseReferenceAuthorityService,
    CourseReferenceResolutionScopeEvidence,
    ReferenceAssetAuthorityEvidence,
    ReferenceRecordDiscrepancy,
    RenderedEntryCandidateBinding,
)
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import RootStorageClass

_MAX_SOURCES = 64
_MAX_ASSETS = 10_000


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityBibliographySource:
    """Configure one explicit owner-private bibliography source."""

    collection_id: str
    bibliography_path: Path = field(repr=False)
    source_id: str
    asserted_source_revision: str | None
    source_path: str
    storage_class: RootStorageClass

    def __post_init__(self) -> None:
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
class CourseReferenceAuthorityRuntimeConfiguration:
    """Configure a concrete References-owned service without parsing in API."""

    course_id: str
    catalog_path: Path = field(repr=False)
    catalog_storage_class: RootStorageClass
    bibliography_sources: tuple[CourseReferenceAuthorityBibliographySource, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...] = ()
    asset_evidence: tuple[ReferenceAssetAuthorityEvidence, ...] = ()

    def __post_init__(self) -> None:
        if type(self.course_id) is not str or not self.course_id:
            raise ValueError("course_id must be nonempty")
        if not isinstance(self.catalog_path, Path):
            raise TypeError("catalog_path must be a Path")
        if not isinstance(self.catalog_storage_class, RootStorageClass):
            raise TypeError("catalog_storage_class must be RootStorageClass")
        _typed_tuple(
            self.bibliography_sources,
            CourseReferenceAuthorityBibliographySource,
            label="bibliography_sources",
            nonempty=True,
        )
        if len(self.bibliography_sources) > _MAX_SOURCES:
            raise ValueError("bibliography source limit exceeded")
        if len({item.collection_id for item in self.bibliography_sources}) != (
            len(self.bibliography_sources)
        ):
            raise ValueError("bibliography collection identities repeat")
        _typed_tuple(
            self.record_discrepancies,
            ReferenceRecordDiscrepancy,
            label="record_discrepancies",
        )
        _typed_tuple(
            self.asset_evidence,
            ReferenceAssetAuthorityEvidence,
            label="asset_evidence",
        )
        if len(self.asset_evidence) > _MAX_ASSETS:
            raise ValueError("asset evidence limit exceeded")
        if len(
            {item.asset_observation_id for item in self.asset_evidence}
        ) != len(self.asset_evidence):
            raise ValueError("asset evidence identities repeat")


class FilesystemCourseReferenceAuthorityEvidenceProvider:
    """Reread and validate configured private sources behind the façade."""

    __slots__ = (
        "_asset_evidence",
        "_course_id",
        "_record_discrepancies",
        "_sources",
    )

    def __init__(
        self,
        *,
        course_id: str,
        bibliography_sources: tuple[
            CourseReferenceAuthorityBibliographySource, ...
        ],
        record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...] = (),
        asset_evidence: tuple[ReferenceAssetAuthorityEvidence, ...] = (),
    ) -> None:
        configuration = CourseReferenceAuthorityRuntimeConfiguration(
            course_id=course_id,
            catalog_path=Path("owner-private-catalog"),
            catalog_storage_class=RootStorageClass.LOCAL,
            bibliography_sources=bibliography_sources,
            record_discrepancies=record_discrepancies,
            asset_evidence=asset_evidence,
        )
        self._course_id = configuration.course_id
        self._sources = configuration.bibliography_sources
        self._record_discrepancies = configuration.record_discrepancies
        self._asset_evidence = configuration.asset_evidence

    def load_course_reference_authority_evidence(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        catalog_candidates: tuple[ReferenceCandidate, ...],
        catalog_observations: tuple[SourceBibliographyObservation, ...],
        catalog_assets: tuple[SourceAssetRecord, ...],
    ) -> CourseReferenceAuthorityOwnerEvidence:
        """Reread exact files and combine them with current schema-5 rows."""
        if scope.course_id != self._course_id:
            from projectkoios.references.course_reference_authority import (
                CourseReferenceAuthorityFailureReason,
                CourseReferenceAuthorityServiceError,
            )

            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.COURSE_NOT_FOUND,
                "course reference authority configuration is unavailable",
            )
        imports = tuple(
            load_bibliography(
                item.bibliography_path,
                source_id=item.source_id,
                source_revision=item.asserted_source_revision,
                source_path=item.source_path,
                storage_class=item.storage_class,
            )
            for item in self._sources
        )
        if any(
            source.asserted_source_revision is not None
            and source.asserted_source_revision.startswith("sha256:")
            and source.asserted_source_revision
            != (
                "sha256:"
                + hashlib.sha256(imported.bibliography_bytes).hexdigest()
            )
            for source, imported in zip(self._sources, imports, strict=True)
        ):
            raise CourseReferenceAuthorityError(
                "bibliography bytes differ from the asserted SHA-256 revision"
            )
        declarations = tuple(
            CandidateBibliographySourceDeclaration(
                collection_id=source.collection_id,
                observations=imported.observations,
            )
            for source, imported in zip(self._sources, imports, strict=True)
        )
        render_result = CandidateBibliographyRenderer().render(
            request=CandidateBibliographyRenderRequest(
                source=CandidateBibliographyExportRequest(
                    sources=declarations,
                )
            )
        )
        candidates = _merge_by_identity(
            (
                *catalog_candidates,
                *(value for item in imports for value in item.candidates),
            ),
            identity_name="candidate_id",
            label="candidate",
        )
        observations = _merge_by_identity(
            (
                *catalog_observations,
                *(value for item in imports for value in item.observations),
            ),
            identity_name="observation_id",
            label="source observation",
        )
        bindings: list[RenderedEntryCandidateBinding] = []
        for entry in render_result.entries:
            matches = tuple(
                candidate
                for candidate in candidates
                if candidate.source_observation_ids
                == entry.source_observation_ids
            )
            if len(matches) != 1:
                continue
            bindings.append(
                RenderedEntryCandidateBinding(
                    reference_locator=entry.entry_id,
                    rendered_entry_id=entry.entry_id,
                    candidate_id=matches[0].candidate_id,
                    source_observation_ids=entry.source_observation_ids,
                )
            )
        assets = self._current_asset_evidence(catalog_assets)
        return CourseReferenceAuthorityOwnerEvidence(
            render_result=render_result,
            candidates=candidates,
            observations=observations,
            rendered_candidate_bindings=tuple(bindings),
            record_discrepancies=self._record_discrepancies,
            assets=assets,
        )

    def _current_asset_evidence(
        self,
        catalog_assets: tuple[SourceAssetRecord, ...],
    ) -> tuple[ReferenceAssetAuthorityEvidence, ...]:
        configured = {
            item.asset_observation_id: item for item in self._asset_evidence
        }
        current = {
            ReferenceAssetAuthorityEvidence.from_asset(
                item
            ).asset_observation_id: item
            for item in catalog_assets
        }
        if not set(configured).issubset(current):
            raise CourseReferenceAuthorityError(
                "configured runtime asset evidence is absent from schema-5"
            )
        return tuple(
            configured.get(
                observation_id,
                ReferenceAssetAuthorityEvidence.from_asset(asset),
            )
            for observation_id, asset in sorted(current.items())
        )


def open_course_reference_authority_service(
    *,
    configuration: CourseReferenceAuthorityRuntimeConfiguration,
) -> CourseReferenceAuthorityService:
    """Open the concrete API façade without creating or migrating a catalog."""
    if type(configuration) is not CourseReferenceAuthorityRuntimeConfiguration:
        raise TypeError(
            "configuration must be CourseReferenceAuthorityRuntimeConfiguration"
        )
    catalog = ReferenceCatalog(
        configuration.catalog_path,
        storage_class=configuration.catalog_storage_class,
    )
    provider = FilesystemCourseReferenceAuthorityEvidenceProvider(
        course_id=configuration.course_id,
        bibliography_sources=configuration.bibliography_sources,
        record_discrepancies=configuration.record_discrepancies,
        asset_evidence=configuration.asset_evidence,
    )
    return CourseReferenceAuthorityService(
        catalog=catalog,
        provider=provider,
    )


def _merge_by_identity[T](
    values: tuple[T, ...],
    *,
    identity_name: str,
    label: str,
) -> tuple[T, ...]:
    by_id: dict[str, T] = {}
    for item in values:
        identity = getattr(item, identity_name)
        existing = by_id.get(identity)
        if existing is not None and existing != item:
            raise CourseReferenceAuthorityError(
                f"{label} identity has conflicting content"
            )
        by_id[identity] = item
    return tuple(by_id[key] for key in sorted(by_id))


def _typed_tuple(
    values: tuple[object, ...],
    expected: type[object],
    *,
    label: str,
    nonempty: bool = False,
) -> None:
    if type(values) is not tuple or any(
        type(item) is not expected for item in values
    ):
        raise TypeError(f"{label} must be an exact typed tuple")
    if nonempty and not values:
        raise ValueError(f"{label} must not be empty")
