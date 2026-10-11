"""HTTP-safe immutable transport for reference-identity authority."""

from __future__ import annotations

import json
from dataclasses import dataclass

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.review import (
    ReferenceIdentityDecision,
    ReviewActorKind,
    ReviewActorProvenance,
    ReviewAuthorityScope,
)

from ..authority.identity_preview import (
    ReferenceIdentityDecisionPreviewActionizer,
    ReferenceIdentityDecisionPreviewRequest,
)
from ..authority.identity_put import (
    PutReferenceIdentityDecisionActionizer,
    PutReferenceIdentityDecisionRequest,
)
from ..authority.scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)
from ..authority.service import (
    CourseReferenceAuthorityFailureReason,
    CourseReferenceAuthorityServiceError,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceIdentityPreviewTransportRequest(DataObjectActionRequest):
    """Carry one HTTP-safe identity preview request plus trusted scope."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    expected_queue_id: str
    expected_item_revision_id: str
    disposition: str
    target_state_projection_id: str | None
    canonical_citekey: str | None
    alias_citekeys: tuple[str, ...]
    selected_record_match_ids: tuple[str, ...]
    expected_current_decision_id: str | None

    def __post_init__(self) -> None:
        """Validate immutable primitive transport values."""
        _identity_values(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceIdentityPreviewTransportResult(DataObjectActionResult):
    """Return one owner-generated identity preview as a JSON object."""

    body_json: str

    def __post_init__(self) -> None:
        """Validate the immutable JSON response body."""
        _json_object(self.body_json)


class ReferenceIdentityPreviewTransportActionizer(
    DataObjectActionizer[
        ReferenceIdentityPreviewTransportRequest,
        ReferenceIdentityPreviewTransportResult,
    ]
):
    """Adapt primitive transport input to the owner preview action."""

    __slots__ = ("_preview",)

    def __init__(
        self,
        *,
        preview: ReferenceIdentityDecisionPreviewActionizer,
    ) -> None:
        """Bind the sole identity-preview capability."""
        if type(preview) is not ReferenceIdentityDecisionPreviewActionizer:
            raise TypeError("preview has an invalid type")
        self._preview = preview

    def action(
        self,
        *,
        request: ReferenceIdentityPreviewTransportRequest,
    ) -> ReferenceIdentityPreviewTransportResult:
        """Return one JSON-safe owner preview with freshness checks."""
        if type(request) is not ReferenceIdentityPreviewTransportRequest:
            raise TypeError("request has an invalid type")
        result = self._preview.action(request=_preview_request(request))
        _expected_projection(
            actual_queue_id=result.queue_id,
            actual_item_revision_id=result.item_revision_id,
            expected_queue_id=request.expected_queue_id,
            expected_item_revision_id=request.expected_item_revision_id,
        )
        return ReferenceIdentityPreviewTransportResult(
            body_json=_body(
                {
                    "alias_citekeys": result.alias_citekeys,
                    "canonical_citekey": result.canonical_citekey,
                    "disposition": result.disposition.name,
                    "expected_current_decision_id": (
                        result.expected_current_decision_id
                    ),
                    "item_revision_id": result.item_revision_id,
                    "preview_id": result.preview_id,
                    "queue_id": result.queue_id,
                    "request_id": result.request_id,
                    "result_id": result.result_id,
                    "selected_record_match_ids": (
                        result.selected_record_match_ids
                    ),
                    "selection_id": result.selection_id,
                    "target_state_projection_id": (
                        result.target_state_projection_id
                    ),
                }
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceIdentityPutTransportRequest(DataObjectActionRequest):
    """Carry one HTTP-safe idempotent identity PUT plus trusted scope."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    idempotency_key: str
    expected_queue_id: str
    expected_item_revision_id: str
    expected_preview_id: str
    expected_preview_result_id: str
    expected_current_decision_id: str | None
    disposition: str
    target_state_projection_id: str | None
    canonical_citekey: str | None
    alias_citekeys: tuple[str, ...]
    selected_record_match_ids: tuple[str, ...]
    rationale: str
    decided_at: str
    actor_id: str
    actor_verification_record_id: str
    actor_verification_method: str

    def __post_init__(self) -> None:
        """Validate immutable primitive PUT transport values."""
        _identity_values(self)
        for label, value in (
            ("idempotency_key", self.idempotency_key),
            ("expected_preview_id", self.expected_preview_id),
            ("expected_preview_result_id", self.expected_preview_result_id),
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
class ReferenceIdentityPutTransportResult(DataObjectActionResult):
    """Return one verified identity PUT receipt as a JSON object."""

    body_json: str

    def __post_init__(self) -> None:
        """Validate the immutable JSON response body."""
        _json_object(self.body_json)


class ReferenceIdentityPutTransportActionizer(
    DataObjectActionizer[
        ReferenceIdentityPutTransportRequest,
        ReferenceIdentityPutTransportResult,
    ]
):
    """Adapt primitive transport input to one atomic identity PUT."""

    __slots__ = ("_put",)

    def __init__(
        self,
        *,
        put: PutReferenceIdentityDecisionActionizer,
    ) -> None:
        """Bind the sole atomic identity-PUT capability."""
        if type(put) is not PutReferenceIdentityDecisionActionizer:
            raise TypeError("put has an invalid type")
        self._put = put

    def action(
        self,
        *,
        request: ReferenceIdentityPutTransportRequest,
    ) -> ReferenceIdentityPutTransportResult:
        """Return one JSON-safe receipt after the atomic owner PUT."""
        if type(request) is not ReferenceIdentityPutTransportRequest:
            raise TypeError("request has an invalid type")
        preview_request = _preview_request(request)
        result = self._put.action(
            request=PutReferenceIdentityDecisionRequest(
                preview_request=preview_request,
                expected_preview_id=request.expected_preview_id,
                expected_preview_result_id=(request.expected_preview_result_id),
                expected_queue_id=request.expected_queue_id,
                expected_item_revision_id=request.expected_item_revision_id,
                actor=ReviewActorProvenance(
                    actor_id=request.actor_id,
                    actor_kind=ReviewActorKind.PERSON,
                    authority_scope=(
                        ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR
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
        return ReferenceIdentityPutTransportResult(
            body_json=_receipt_body(
                result=result,
                dimension="reference-identity",
                disposition=request.disposition,
            )
        )


def _identity_values(
    request: ReferenceIdentityPreviewTransportRequest
    | ReferenceIdentityPutTransportRequest,
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
        ("disposition", request.disposition),
    ):
        _nonempty(value, field=label)
    try:
        ReferenceIdentityDecision[request.disposition]
    except KeyError as error:
        raise ValueError("disposition is invalid") from error
    for label, values in (
        ("alias_citekeys", request.alias_citekeys),
        ("selected_record_match_ids", request.selected_record_match_ids),
    ):
        if not isinstance(values, tuple) or any(
            type(value) is not str or not value for value in values
        ):
            raise TypeError(f"{label} must be a tuple of nonempty strings")
    for optional_label, optional_value in (
        ("target_state_projection_id", request.target_state_projection_id),
        ("canonical_citekey", request.canonical_citekey),
        (
            "expected_current_decision_id",
            request.expected_current_decision_id,
        ),
    ):
        if optional_value is not None:
            _nonempty(optional_value, field=optional_label)


def _preview_request(
    request: ReferenceIdentityPreviewTransportRequest
    | ReferenceIdentityPutTransportRequest,
) -> ReferenceIdentityDecisionPreviewRequest:
    return ReferenceIdentityDecisionPreviewRequest(
        scope=request.scope,
        selections=request.selections,
        selection_id=request.selection_id,
        disposition=ReferenceIdentityDecision[request.disposition],
        target_state_projection_id=request.target_state_projection_id,
        canonical_citekey=request.canonical_citekey,
        alias_citekeys=request.alias_citekeys,
        selected_record_match_ids=request.selected_record_match_ids,
        expected_current_decision_id=request.expected_current_decision_id,
    )


def _expected_projection(
    *,
    actual_queue_id: str,
    actual_item_revision_id: str,
    expected_queue_id: str,
    expected_item_revision_id: str,
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
