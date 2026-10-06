from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import final

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.assets import (
    AssetCandidate,
    AssetDiscoveryPlan,
    AssetMaterializationResult,
    CanonicalAssetAuthorization,
    SearchRoot,
    materialize_asset_with_result,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.identity import IdentityProjection
from projectkoios.references.io_limits import ASSET_DISCOVERY_IO_LIMITS
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import (
    RootStorageClass,
    read_path_text,
    validate_citekey,
    validate_relative_path,
)

ASSET_APPLICATION_OPERATION_ACTION_ID = (
    "projectkoios.references.asset_application.operation@1"
)


class AssetApplicationError(ValueError):
    """Reject an incomplete or conflicting asset-application request."""


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


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssetApplicationOperationResult(DataObjectActionResult):
    """Bind validated authority and effects for one complete application."""

    request: AssetApplicationOperationRequest
    plan: AssetDiscoveryPlan
    authorization: CanonicalAssetAuthorization
    identity_projection: IdentityProjection
    candidate: AssetCandidate
    catalog_record: SourceAssetRecord
    materialization: AssetMaterializationResult
    catalog_record_present: bool

    def __post_init__(self) -> None:
        for value, expected, label in (
            (
                self.request,
                AssetApplicationOperationRequest,
                "request",
            ),
            (self.plan, AssetDiscoveryPlan, "plan"),
            (
                self.authorization,
                CanonicalAssetAuthorization,
                "authorization",
            ),
            (
                self.identity_projection,
                IdentityProjection,
                "identity_projection",
            ),
            (self.candidate, AssetCandidate, "candidate"),
            (self.catalog_record, SourceAssetRecord, "catalog_record"),
            (
                self.materialization,
                AssetMaterializationResult,
                "materialization",
            ),
        ):
            if type(value) is not expected:
                raise TypeError(f"{label} has an unsupported type")
        if type(self.catalog_record_present) is not bool:
            raise TypeError("catalog_record_present must be a bool")
        if self.authorization.asset_plan_id != self.plan.plan_id:
            raise ValueError("authorization does not bind the returned plan")
        if (
            self.authorization.identity_projection_id
            != self.identity_projection.projection_id
        ):
            raise ValueError(
                "authorization does not bind the returned identity projection"
            )
        if (
            self.candidate.observation_id
            != self.authorization.selected_asset_observation_id
            or self.candidate.proposed_citekey != self.request.citekey
            or (
                self.request.candidate_path is not None
                and self.candidate.relative_path != self.request.candidate_path
            )
        ):
            raise ValueError("returned candidate does not match the request")
        expected_record = SourceAssetRecord(
            candidate_id=self.candidate.candidate_id,
            proposed_citekey=self.candidate.proposed_citekey,
            identity_status=self.candidate.identity_status,
            citekey_status=self.candidate.citekey_status,
            sha256=self.candidate.sha256,
            byte_size=self.candidate.byte_size,
            root_alias="materialized-assets",
            relative_path=f"{self.authorization.canonical_citekey}.pdf",
            rights_status=self.request.rights_status,
            asset_status="authorized-canonical-local-copy",
        )
        if self.catalog_record != expected_record:
            raise ValueError("catalog record differs from the authorized asset")
        if self.materialization.path.name != expected_record.relative_path:
            raise ValueError(
                "materialization path differs from the canonical name"
            )
        if self.catalog_record_present != (self.request.catalog is not None):
            raise ValueError(
                "catalog result differs from the requested capability"
            )


@final
class AssetApplicationOperation(DataObjectActionizer):
    """Apply one authorized asset as an indivisible owner operation."""

    action_id = ASSET_APPLICATION_OPERATION_ACTION_ID

    def action(
        self, *, request: AssetApplicationOperationRequest
    ) -> AssetApplicationOperationResult:
        if type(request) is not AssetApplicationOperationRequest:
            raise TypeError(
                "request must be an AssetApplicationOperationRequest"
            )
        max_json_bytes = ASSET_DISCOVERY_IO_LIMITS.max_json_bytes
        if type(max_json_bytes) is not int or max_json_bytes <= 0:
            raise RuntimeError("max_json_bytes must be a positive integer")
        plan = AssetDiscoveryPlan.from_json(
            read_path_text(
                request.plan,
                label="asset discovery plan",
                root_alias="asset-plan-input",
                storage_class=request.plan_storage_class,
                max_bytes=max_json_bytes,
            )
        )
        authorization = CanonicalAssetAuthorization.from_json(
            read_path_text(
                request.authorization,
                label="canonical asset authorization",
                root_alias="asset-authorization-input",
                storage_class=request.authorization_storage_class,
                max_bytes=max_json_bytes,
            )
        )
        identity_projection = IdentityProjection.from_json(
            read_path_text(
                request.identity_projection,
                label="identity projection",
                root_alias="identity-projection-input",
                storage_class=request.identity_projection_storage_class,
                max_bytes=max_json_bytes,
            )
        )
        matches = tuple(
            item
            for item in plan.candidates
            if item.observation_id
            == authorization.selected_asset_observation_id
            and item.proposed_citekey == request.citekey
            and (
                request.candidate_path is None
                or item.relative_path == request.candidate_path
            )
        )
        if len(matches) != 1:
            raise AssetApplicationError(
                "authorization must select exactly one matching asset"
            )
        candidate = matches[0]
        preflights = tuple(
            item
            for item in plan.root_preflights
            if item.root_alias == candidate.root_alias
        )
        if len(preflights) != 1:
            raise AssetApplicationError(
                "selected asset must have exactly one root preflight"
            )
        catalog_record = SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.identity_status,
            citekey_status=candidate.citekey_status,
            sha256=candidate.sha256,
            byte_size=candidate.byte_size,
            root_alias="materialized-assets",
            relative_path=f"{authorization.canonical_citekey}.pdf",
            rights_status=request.rights_status,
            asset_status="authorized-canonical-local-copy",
        )

        if request.catalog is None:
            materialization = materialize_asset_with_result(
                candidate,
                authorization=authorization,
                plan=plan,
                identity_projection=identity_projection,
                expected_root_preflight=preflights[0],
                roots=request.search_roots,
                destination_directory=request.destination,
                destination_storage_class=request.destination_storage_class,
            )
            catalog_record_present = False
        else:
            if request.catalog_storage_class is None:  # pragma: no cover
                raise RuntimeError("validated catalog capability is incomplete")
            catalog = ReferenceCatalog(
                request.catalog,
                storage_class=request.catalog_storage_class,
            )
            catalog.initialize()
            with catalog.source_asset_recording_transaction(catalog_record):
                materialization = materialize_asset_with_result(
                    candidate,
                    authorization=authorization,
                    plan=plan,
                    identity_projection=identity_projection,
                    expected_root_preflight=preflights[0],
                    roots=request.search_roots,
                    destination_directory=request.destination,
                    destination_storage_class=(
                        request.destination_storage_class
                    ),
                )
            catalog_record_present = True

        return AssetApplicationOperationResult(
            request=request,
            plan=plan,
            authorization=authorization,
            identity_projection=identity_projection,
            candidate=candidate,
            catalog_record=catalog_record,
            materialization=materialization,
            catalog_record_present=catalog_record_present,
        )
