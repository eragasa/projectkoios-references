"""HTTP-safe immutable transport for canonical-asset authority."""

from __future__ import annotations

import json
from dataclasses import dataclass

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.review import (
    CanonicalAssetDecision,
    ReviewActorKind,
    ReviewActorProvenance,
    ReviewAuthorityScope,
)

from ..authority.asset_preview import (
    CanonicalAssetDecisionPreviewActionizer,
    CanonicalAssetDecisionPreviewRequest,
)
from ..authority.asset_put import (
    PutCanonicalAssetDecisionActionizer,
    PutCanonicalAssetDecisionRequest,
)
from ..authority.plans import CanonicalAssetCompetitorDisposition
from ..authority.scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)
from ..authority.service import (
    CourseReferenceAuthorityFailureReason,
    CourseReferenceAuthorityServiceError,
)

AssetCompetitorTransportValue = tuple[str, str, str]


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetPreviewTransportRequest(DataObjectActionRequest):
    """Carry one HTTP-safe asset preview request plus trusted scope."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    expected_queue_id: str
    expected_item_revision_id: str
    expected_identity_state_projection_id: str
    disposition: str
    competitors: tuple[AssetCompetitorTransportValue, ...]
    expected_current_decision_id: str | None

    def __post_init__(self) -> None:
        """Validate immutable primitive transport values."""
        _asset_values(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetPreviewTransportResult(DataObjectActionResult):
    """Return one owner-generated asset preview as a JSON object."""

    body_json: str

    def __post_init__(self) -> None:
        """Validate the immutable JSON response body."""
        _json_object(self.body_json)


class CanonicalAssetPreviewTransportActionizer(
    DataObjectActionizer[
        CanonicalAssetPreviewTransportRequest,
        CanonicalAssetPreviewTransportResult,
    ]
):
    """Adapt primitive transport input to the owner asset preview."""

    __slots__ = ("_preview",)

    def __init__(
        self,
        *,
        preview: CanonicalAssetDecisionPreviewActionizer,
    ) -> None:
        """Bind the sole canonical-asset-preview capability."""
        if type(preview) is not CanonicalAssetDecisionPreviewActionizer:
            raise TypeError("preview has an invalid type")
        self._preview = preview

    def action(
        self,
        *,
        request: CanonicalAssetPreviewTransportRequest,
    ) -> CanonicalAssetPreviewTransportResult:
        """Return one JSON-safe owner preview with freshness checks."""
        if type(request) is not CanonicalAssetPreviewTransportRequest:
            raise TypeError("request has an invalid type")
        result = self._preview.action(request=_preview_request(request))
        _expected_projection(
            actual_queue_id=result.queue_id,
            actual_item_revision_id=result.item_revision_id,
            actual_identity_projection_id=(result.identity_state_projection_id),
            expected_queue_id=request.expected_queue_id,
            expected_item_revision_id=request.expected_item_revision_id,
            expected_identity_projection_id=(
                request.expected_identity_state_projection_id
            ),
        )
        return CanonicalAssetPreviewTransportResult(
            body_json=_body(
                {
                    "competitors": tuple(
                        {
                            "asset_observation_id": (
                                competitor.asset_observation_id
                            ),
                            "disposition": competitor.disposition.name,
                            "rationale": competitor.rationale,
                        }
                        for competitor in result.competitor_dispositions
                    ),
                    "disposition": result.disposition.name,
                    "expected_current_decision_id": (
                        result.expected_current_decision_id
                    ),
                    "identity_state_projection_id": (
                        result.identity_state_projection_id
                    ),
                    "item_revision_id": result.item_revision_id,
                    "plan_id": result.plan_id,
                    "preview_id": result.preview_id,
                    "queue_id": result.queue_id,
                    "request_id": result.request_id,
                    "result_id": result.result_id,
                    "selected_asset_observation_id": (
                        result.selected_asset_observation_id
                    ),
                    "selection_id": result.selection_id,
                }
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetPutTransportRequest(DataObjectActionRequest):
    """Carry one HTTP-safe idempotent asset PUT plus trusted scope."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    idempotency_key: str
    expected_queue_id: str
    expected_item_revision_id: str
    expected_preview_id: str
    expected_preview_result_id: str
    expected_identity_state_projection_id: str
    expected_asset_plan_id: str
    expected_current_decision_id: str | None
    disposition: str
    competitors: tuple[AssetCompetitorTransportValue, ...]
    rationale: str
    decided_at: str
    actor_id: str
    actor_verification_record_id: str
    actor_verification_method: str

    def __post_init__(self) -> None:
        """Validate immutable primitive PUT transport values."""
        _asset_values(self)
        for label, value in (
            ("idempotency_key", self.idempotency_key),
            ("expected_preview_id", self.expected_preview_id),
            ("expected_preview_result_id", self.expected_preview_result_id),
            ("expected_asset_plan_id", self.expected_asset_plan_id),
            ("rationale", self.rationale),
            ("decided_at", self.decided_at),
            ("actor_id", self.actor_id),
            (
                "actor_verification_record_id",
                self.actor_verification_record_id,
            ),
            ("actor_verification_method", self.actor_verification_method),
        ):
            _nonempty(value, field=label)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetPutTransportResult(DataObjectActionResult):
    """Return one verified canonical-asset PUT receipt as JSON."""

    body_json: str

    def __post_init__(self) -> None:
        """Validate the immutable JSON response body."""
        _json_object(self.body_json)


class CanonicalAssetPutTransportActionizer(
    DataObjectActionizer[
        CanonicalAssetPutTransportRequest,
        CanonicalAssetPutTransportResult,
    ]
):
    """Adapt primitive transport input to one atomic asset PUT."""

    __slots__ = ("_put",)

    def __init__(
        self,
        *,
        put: PutCanonicalAssetDecisionActionizer,
    ) -> None:
        """Bind the sole atomic canonical-asset-PUT capability."""
        if type(put) is not PutCanonicalAssetDecisionActionizer:
            raise TypeError("put has an invalid type")
        self._put = put

    def action(
        self,
        *,
        request: CanonicalAssetPutTransportRequest,
    ) -> CanonicalAssetPutTransportResult:
        """Return one JSON-safe receipt after the atomic owner PUT."""
        if type(request) is not CanonicalAssetPutTransportRequest:
            raise TypeError("request has an invalid type")
        result = self._put.action(
            request=PutCanonicalAssetDecisionRequest(
                preview_request=_preview_request(request),
                expected_preview_id=request.expected_preview_id,
                expected_preview_result_id=(request.expected_preview_result_id),
                expected_queue_id=request.expected_queue_id,
                expected_item_revision_id=request.expected_item_revision_id,
                expected_identity_state_projection_id=(
                    request.expected_identity_state_projection_id
                ),
                expected_plan_id=request.expected_asset_plan_id,
                actor=ReviewActorProvenance(
                    actor_id=request.actor_id,
                    actor_kind=ReviewActorKind.PERSON,
                    authority_scope=(
                        ReviewAuthorityScope.CANONICAL_ASSET_CURATOR
                    ),
                    authority_domain="projectkoios-references",
                    verification_record_id=(
                        request.actor_verification_record_id
                    ),
                    verification_method=request.actor_verification_method,
                ),
                rationale=request.rationale,
                decided_at=request.decided_at,
                idempotency_key=request.idempotency_key,
            )
        )
        return CanonicalAssetPutTransportResult(
            body_json=_receipt_body(
                result=result,
                dimension="canonical-asset",
                disposition=request.disposition,
            )
        )


def _asset_values(
    request: CanonicalAssetPreviewTransportRequest
    | CanonicalAssetPutTransportRequest,
) -> None:
    if type(request.scope) is not CourseReferenceResolutionScopeEvidence:
        raise TypeError("scope has an invalid type")
    if not isinstance(request.selections, tuple) or any(
        type(item) is not CourseReferenceSelectionEvidence
        for item in request.selections
    ):
        raise TypeError("selections must be an exact typed tuple")
    for label, value in (
        ("selection_id", request.selection_id),
        ("expected_queue_id", request.expected_queue_id),
        ("expected_item_revision_id", request.expected_item_revision_id),
        (
            "expected_identity_state_projection_id",
            request.expected_identity_state_projection_id,
        ),
        ("disposition", request.disposition),
    ):
        _nonempty(value, field=label)
    try:
        CanonicalAssetDecision[request.disposition]
    except KeyError as error:
        raise ValueError("disposition is invalid") from error
    if not isinstance(request.competitors, tuple):
        raise TypeError("competitors must be a tuple")
    for competitor in request.competitors:
        if not isinstance(competitor, tuple) or len(competitor) != 3:
            raise TypeError("competitor must be an exact three-string tuple")
        for value in competitor:
            _nonempty(value, field="competitor value")
        try:
            CanonicalAssetDecision[competitor[1]]
        except KeyError as error:
            raise ValueError("competitor disposition is invalid") from error
    if request.expected_current_decision_id is not None:
        _nonempty(
            request.expected_current_decision_id,
            field="expected_current_decision_id",
        )


def _preview_request(
    request: CanonicalAssetPreviewTransportRequest
    | CanonicalAssetPutTransportRequest,
) -> CanonicalAssetDecisionPreviewRequest:
    return CanonicalAssetDecisionPreviewRequest(
        scope=request.scope,
        selections=request.selections,
        selection_id=request.selection_id,
        disposition=CanonicalAssetDecision[request.disposition],
        competitor_dispositions=tuple(
            CanonicalAssetCompetitorDisposition(
                asset_observation_id=competitor[0],
                disposition=CanonicalAssetDecision[competitor[1]],
                rationale=competitor[2],
            )
            for competitor in request.competitors
        ),
        expected_current_decision_id=request.expected_current_decision_id,
    )


def _expected_projection(
    *,
    actual_queue_id: str,
    actual_item_revision_id: str,
    actual_identity_projection_id: str,
    expected_queue_id: str,
    expected_item_revision_id: str,
    expected_identity_projection_id: str,
) -> None:
    if actual_queue_id != expected_queue_id:
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
            "course reference queue evidence is stale",
        )
    if actual_item_revision_id != expected_item_revision_id:
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.REVISION_STALE,
            "course reference item revision is stale",
        )
    if actual_identity_projection_id != expected_identity_projection_id:
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.REVISION_STALE,
            "reference identity projection is stale",
        )


def _receipt_body(*, result: object, dimension: str, disposition: str) -> str:
    from ..authority.put_result import ReferenceAuthorityDecisionPutResult

    if type(result) is not ReferenceAuthorityDecisionPutResult:
        raise TypeError("PUT result has an invalid type")
    return _body(
        {
            "current_decision_id": result.current_decision_id,
            "current_state_projection_id": (result.current_state_projection_id),
            "decision_append_request_id": (result.decision_append_request_id),
            "decision_id": result.decision_id,
            "dimension": dimension,
            "disposition": disposition,
            "preview_id": result.preview_id,
            "put_request_id": result.put_request_id,
            "receipt_id": result.receipt_id,
            "refreshed_item_revision_id": (result.refreshed_item_revision_id),
            "refreshed_queue_id": result.refreshed_queue_id,
            "result_id": result.result_id,
            "state_projection_id": result.state_projection_id,
        }
    )


def _body(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object(value: str) -> None:
    if type(value) is not str:
        raise TypeError("body_json must be str")
    decoded: object = json.loads(value)
    if type(decoded) is not dict:
        raise ValueError("transport body must be a JSON object")


def _nonempty(value: str, *, field: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{field} must be a nonempty string")
