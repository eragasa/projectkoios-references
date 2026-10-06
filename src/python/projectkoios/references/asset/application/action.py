from __future__ import annotations

from typing import final

from projectkoios.base import DataObjectActionizer
from projectkoios.references.assets import (
    AssetDiscoveryPlan,
    CanonicalAssetAuthorization,
    materialize_asset_with_result,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.identity import IdentityProjection
from projectkoios.references.io_limits import ASSET_DISCOVERY_IO_LIMITS
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import read_path_text

from .error import AssetApplicationError
from .request import AssetApplicationOperationRequest
from .result import AssetApplicationOperationResult

ASSET_APPLICATION_OPERATION_ACTION_ID = (
    "projectkoios.references.asset.application@1"
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
