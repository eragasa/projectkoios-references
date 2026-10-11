"""Filesystem-backed runtime composition for course reference authority."""

from __future__ import annotations

import hashlib
import json
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
    IngestionArtifactAuthorityLink,
    ReferenceAssetAuthorityEvidence,
    ReferenceRecordDiscrepancy,
    RenderedEntryCandidateBinding,
    RuntimeAssetAvailability,
)
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    PathLimitError,
    PathSafetyError,
    PlaceholderStatus,
    RootStorageClass,
    read_path_bytes,
)

_MAX_SOURCES = 64
_MAX_ASSETS = 10_000
_MAX_LINKAGE_BYTES = 10_000_000
_MAX_ASSET_OBSERVATION_BYTES = 4_000_000_000


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
class CourseReferenceAuthorityAssetRoot:
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
        if type(self.root_alias) is not str or not self.root_alias:
            raise ValueError("root_alias must be nonempty")
        if not isinstance(self.root_path, Path):
            raise TypeError("root_path must be a Path")
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
    asset_roots: tuple[CourseReferenceAuthorityAssetRoot, ...] = ()
    asset_linkage_path: Path | None = field(default=None, repr=False)
    asset_linkage_storage_class: RootStorageClass = RootStorageClass.LOCAL
    asset_linkage_placeholder_probe: CloudPlaceholderProbe | None = field(
        default=None,
        repr=False,
        compare=False,
    )

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
            self.asset_roots,
            CourseReferenceAuthorityAssetRoot,
            label="asset_roots",
        )
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


@dataclass(frozen=True, slots=True, kw_only=True)
class _AssetLinkage:
    asset_observation_id: str
    document_binding_ids: tuple[str, ...]
    ingestion_evidence_ids: tuple[str, ...]
    ingestion_artifact_links: tuple[IngestionArtifactAuthorityLink, ...]


class FilesystemCourseReferenceAuthorityEvidenceProvider:
    """Reread private sources, assets, and linkage behind the façade."""

    __slots__ = (
        "_asset_linkage_path",
        "_asset_linkage_placeholder_probe",
        "_asset_linkage_storage_class",
        "_asset_roots",
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
        asset_roots: tuple[CourseReferenceAuthorityAssetRoot, ...] = (),
        asset_linkage_path: Path | None = None,
        asset_linkage_storage_class: RootStorageClass = RootStorageClass.LOCAL,
        asset_linkage_placeholder_probe: CloudPlaceholderProbe | None = None,
    ) -> None:
        configuration = CourseReferenceAuthorityRuntimeConfiguration(
            course_id=course_id,
            catalog_path=Path("owner-private-catalog"),
            catalog_storage_class=RootStorageClass.LOCAL,
            bibliography_sources=bibliography_sources,
            record_discrepancies=record_discrepancies,
            asset_roots=asset_roots,
            asset_linkage_path=asset_linkage_path,
            asset_linkage_storage_class=asset_linkage_storage_class,
            asset_linkage_placeholder_probe=(asset_linkage_placeholder_probe),
        )
        self._course_id = configuration.course_id
        self._sources = configuration.bibliography_sources
        self._record_discrepancies = configuration.record_discrepancies
        self._asset_roots = {
            item.root_alias: item for item in configuration.asset_roots
        }
        self._asset_linkage_path = configuration.asset_linkage_path
        self._asset_linkage_storage_class = (
            configuration.asset_linkage_storage_class
        )
        self._asset_linkage_placeholder_probe = (
            configuration.asset_linkage_placeholder_probe
        )

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
        linkages = self._load_asset_linkages()
        current = {
            ReferenceAssetAuthorityEvidence.from_asset(
                item
            ).asset_observation_id: item
            for item in catalog_assets
        }
        if not set(linkages).issubset(current):
            raise CourseReferenceAuthorityError(
                "configured asset linkage is absent from schema-5"
            )
        return tuple(
            self._observe_asset(
                asset=asset,
                linkage=linkages.get(observation_id),
            )
            for observation_id, asset in sorted(current.items())
        )

    def _observe_asset(
        self,
        *,
        asset: SourceAssetRecord,
        linkage: _AssetLinkage | None,
    ) -> ReferenceAssetAuthorityEvidence:
        root = self._asset_roots.get(asset.root_alias)
        availability = RuntimeAssetAvailability.UNKNOWN
        runtime_evidence_id: str | None = None
        if root is not None:
            availability, runtime_evidence_id = _observe_runtime_asset(
                asset=asset,
                root=root,
            )
        return ReferenceAssetAuthorityEvidence.from_asset(
            asset,
            runtime_availability=availability,
            runtime_evidence_id=runtime_evidence_id,
            document_binding_ids=(
                () if linkage is None else linkage.document_binding_ids
            ),
            ingestion_evidence_ids=(
                () if linkage is None else linkage.ingestion_evidence_ids
            ),
            ingestion_artifact_links=(
                () if linkage is None else linkage.ingestion_artifact_links
            ),
        )

    def _load_asset_linkages(self) -> dict[str, _AssetLinkage]:
        if self._asset_linkage_path is None:
            return {}
        content = read_path_bytes(
            self._asset_linkage_path,
            label="course reference asset linkage",
            root_alias="course-reference-asset-linkage",
            storage_class=self._asset_linkage_storage_class,
            placeholder_probe=self._asset_linkage_placeholder_probe,
            max_bytes=_MAX_LINKAGE_BYTES,
        )
        try:
            payload = json.loads(content.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CourseReferenceAuthorityError(
                "asset linkage evidence is not valid UTF-8 JSON"
            ) from error
        if (
            type(payload) is not dict
            or set(payload) != {"assets", "schema_version"}
            or payload["schema_version"] != 1
            or type(payload["assets"]) is not list
            or len(payload["assets"]) > _MAX_ASSETS
        ):
            raise CourseReferenceAuthorityError(
                "asset linkage evidence has an unsupported envelope"
            )
        values = tuple(_parse_asset_linkage(item) for item in payload["assets"])
        by_id = {item.asset_observation_id: item for item in values}
        if len(by_id) != len(values):
            raise CourseReferenceAuthorityError(
                "asset linkage observation identities repeat"
            )
        return by_id


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
        asset_roots=configuration.asset_roots,
        asset_linkage_path=configuration.asset_linkage_path,
        asset_linkage_storage_class=(configuration.asset_linkage_storage_class),
        asset_linkage_placeholder_probe=(
            configuration.asset_linkage_placeholder_probe
        ),
    )
    return CourseReferenceAuthorityService(
        catalog=catalog,
        provider=provider,
    )


def _observe_runtime_asset(
    *,
    asset: SourceAssetRecord,
    root: CourseReferenceAuthorityAssetRoot,
) -> tuple[RuntimeAssetAvailability, str | None]:
    try:
        authorized = AuthorizedRoot.existing(
            root.root_path,
            label="course reference asset root",
            root_alias=root.root_alias,
            storage_class=root.storage_class,
            placeholder_probe=root.placeholder_probe,
        )
        preflight = authorized.preflight_file(asset.relative_path)
    except OSError, PathSafetyError:
        return RuntimeAssetAvailability.UNKNOWN, None
    if preflight.status is PlaceholderStatus.MISSING:
        return (
            RuntimeAssetAvailability.UNAVAILABLE,
            _runtime_asset_evidence_id(
                asset=asset,
                availability=RuntimeAssetAvailability.UNAVAILABLE,
                observation_status="missing",
                observed_sha256=None,
                observed_byte_size=None,
            ),
        )
    if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
        return RuntimeAssetAvailability.UNKNOWN, None
    if asset.byte_size > _MAX_ASSET_OBSERVATION_BYTES:
        return RuntimeAssetAvailability.UNKNOWN, None
    try:
        observation = authorized.observe_file(
            asset.relative_path,
            max_bytes=asset.byte_size,
        )
    except FileNotFoundError:
        return (
            RuntimeAssetAvailability.UNAVAILABLE,
            _runtime_asset_evidence_id(
                asset=asset,
                availability=RuntimeAssetAvailability.UNAVAILABLE,
                observation_status="missing-during-observation",
                observed_sha256=None,
                observed_byte_size=None,
            ),
        )
    except PathLimitError:
        return (
            RuntimeAssetAvailability.UNAVAILABLE,
            _runtime_asset_evidence_id(
                asset=asset,
                availability=RuntimeAssetAvailability.UNAVAILABLE,
                observation_status="size-exceeded",
                observed_sha256=None,
                observed_byte_size=None,
            ),
        )
    except OSError, PathSafetyError:
        return RuntimeAssetAvailability.UNKNOWN, None
    availability = (
        RuntimeAssetAvailability.AVAILABLE
        if observation.sha256 == asset.sha256
        and observation.byte_size == asset.byte_size
        else RuntimeAssetAvailability.UNAVAILABLE
    )
    return (
        availability,
        _runtime_asset_evidence_id(
            asset=asset,
            availability=availability,
            observation_status=(
                "matched"
                if availability is RuntimeAssetAvailability.AVAILABLE
                else "digest-or-size-changed"
            ),
            observed_sha256=observation.sha256,
            observed_byte_size=observation.byte_size,
        ),
    )


def _runtime_asset_evidence_id(
    *,
    asset: SourceAssetRecord,
    availability: RuntimeAssetAvailability,
    observation_status: str,
    observed_sha256: str | None,
    observed_byte_size: int | None,
) -> str:
    material = json.dumps(
        {
            "asset_observation_id": (
                ReferenceAssetAuthorityEvidence.from_asset(
                    asset
                ).asset_observation_id
            ),
            "availability": availability.value,
            "observation_status": observation_status,
            "observed_byte_size": observed_byte_size,
            "observed_sha256": observed_sha256,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return (
        "runtime-asset-evidence:sha256:" + hashlib.sha256(material).hexdigest()
    )


def _parse_asset_linkage(value: object) -> _AssetLinkage:
    required = {
        "asset_observation_id",
        "document_binding_ids",
        "ingestion_artifact_links",
        "ingestion_evidence_ids",
    }
    if type(value) is not dict or set(value) != required:
        raise CourseReferenceAuthorityError(
            "asset linkage entry has unsupported fields"
        )
    asset_observation_id = value["asset_observation_id"]
    if type(asset_observation_id) is not str:
        raise CourseReferenceAuthorityError(
            "asset linkage observation identity is invalid"
        )
    raw_links = value["ingestion_artifact_links"]
    if type(raw_links) is not list or len(raw_links) > _MAX_ASSETS:
        raise CourseReferenceAuthorityError(
            "asset Ingestion links have invalid bounds"
        )
    links = tuple(
        _parse_ingestion_link(
            item,
            asset_observation_id=asset_observation_id,
        )
        for item in raw_links
    )
    links = tuple(sorted(links, key=lambda item: item.link_id))
    return _AssetLinkage(
        asset_observation_id=asset_observation_id,
        document_binding_ids=_identity_list(
            value["document_binding_ids"],
            label="document_binding_ids",
        ),
        ingestion_evidence_ids=_identity_list(
            value["ingestion_evidence_ids"],
            label="ingestion_evidence_ids",
        ),
        ingestion_artifact_links=links,
    )


def _parse_ingestion_link(
    value: object,
    *,
    asset_observation_id: str,
) -> IngestionArtifactAuthorityLink:
    required = {
        "artifact_verification_result_id",
        "document_id",
        "source_id",
    }
    if (
        type(value) is not dict
        or set(value) != required
        or any(type(value[name]) is not str for name in required)
    ):
        raise CourseReferenceAuthorityError(
            "Ingestion artifact link has unsupported fields"
        )
    return IngestionArtifactAuthorityLink(
        asset_observation_id=asset_observation_id,
        source_id=value["source_id"],
        document_id=value["document_id"],
        artifact_verification_result_id=(
            value["artifact_verification_result_id"]
        ),
    )


def _identity_list(value: object, *, label: str) -> tuple[str, ...]:
    if (
        type(value) is not list
        or len(value) > _MAX_ASSETS
        or any(type(item) is not str for item in value)
    ):
        raise CourseReferenceAuthorityError(f"{label} has invalid bounds")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise CourseReferenceAuthorityError(
            f"{label} must use unique lexical order"
        )
    return result


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
