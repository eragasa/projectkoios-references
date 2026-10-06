from __future__ import annotations

from dataclasses import dataclass
from typing import final

from projectkoios.base import DataObjectActionResult
from projectkoios.references.assets import (
    AssetCandidate,
    AssetDiscoveryPlan,
    AssetMaterializationResult,
    CanonicalAssetAuthorization,
)
from projectkoios.references.identity import IdentityProjection
from projectkoios.references.models import SourceAssetRecord

from .request import AssetApplicationOperationRequest


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
