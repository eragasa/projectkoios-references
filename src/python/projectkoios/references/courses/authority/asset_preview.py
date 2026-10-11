"""Typed canonical-asset consequence preview owner operation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.review import (
    CanonicalAssetDecision,
)

from .authority_state import (
    CurrentReviewDecisionHead,
)
from .errors import CourseReferenceAuthorityError
from .plans import (
    CanonicalAssetCompetitorDisposition,
    CanonicalAssetDecisionPreview,
    CanonicalAssetEvidencePlan,
)
from .queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
)
from .scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)
from .service import (
    CourseReferenceAuthorityFailureReason,
    CourseReferenceAuthorityLoadActionizer,
    CourseReferenceAuthorityLoadRequest,
    CourseReferenceAuthorityServiceError,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetDecisionPreviewRequest(DataObjectActionRequest):
    """Request one owner-generated complete asset consequence preview."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    disposition: CanonicalAssetDecision
    competitor_dispositions: tuple[CanonicalAssetCompetitorDisposition, ...]
    expected_current_decision_id: str | None
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        if not isinstance(self.selections, tuple) or any(
            type(item) is not CourseReferenceSelectionEvidence
            for item in self.selections
        ):
            raise TypeError("selections must be an exact typed tuple")
        _content_id(self.selection_id, field="selection_id")
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("asset disposition is invalid")
        if not isinstance(self.competitor_dispositions, tuple) or any(
            type(item) is not CanonicalAssetCompetitorDisposition
            for item in self.competitor_dispositions
        ):
            raise TypeError(
                "competitor_dispositions must be an exact typed tuple"
            )
        if self.expected_current_decision_id is not None:
            _content_id(
                self.expected_current_decision_id,
                field="expected_current_decision_id",
            )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "canonical-asset-decision-preview-request",
                {
                    "competitor_dispositions": (self.competitor_dispositions),
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "scope_id": self.scope.scope_id,
                    "selection_ids": tuple(
                        item.selection_id for item in self.selections
                    ),
                    "selection_id": self.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetDecisionPreviewResult(DataObjectActionResult):
    """Expose only the safe asset consequence and CAS identities."""

    request_id: str
    preview_id: str
    plan_id: str
    selection_id: str
    disposition: CanonicalAssetDecision
    competitor_dispositions: tuple[CanonicalAssetCompetitorDisposition, ...]
    selected_asset_observation_id: str | None
    expected_current_decision_id: str | None
    identity_state_projection_id: str
    queue_id: str
    item_revision_id: str
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        for label, value in (
            ("request_id", self.request_id),
            ("preview_id", self.preview_id),
            ("plan_id", self.plan_id),
            ("selection_id", self.selection_id),
            (
                "identity_state_projection_id",
                self.identity_state_projection_id,
            ),
            ("queue_id", self.queue_id),
            ("item_revision_id", self.item_revision_id),
        ):
            _content_id(value, field=label)
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("asset disposition is invalid")
        if not isinstance(self.competitor_dispositions, tuple) or any(
            type(item) is not CanonicalAssetCompetitorDisposition
            for item in self.competitor_dispositions
        ):
            raise TypeError(
                "competitor_dispositions must be an exact typed tuple"
            )
        if self.selected_asset_observation_id is not None:
            _content_id(
                self.selected_asset_observation_id,
                field="selected_asset_observation_id",
            )
        if self.expected_current_decision_id is not None:
            _content_id(
                self.expected_current_decision_id,
                field="expected_current_decision_id",
            )
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "canonical-asset-decision-preview-result",
                {
                    "competitor_dispositions": (self.competitor_dispositions),
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "identity_state_projection_id": (
                        self.identity_state_projection_id
                    ),
                    "item_revision_id": self.item_revision_id,
                    "plan_id": self.plan_id,
                    "preview_id": self.preview_id,
                    "queue_id": self.queue_id,
                    "request_id": self.request_id,
                    "selected_asset_observation_id": (
                        self.selected_asset_observation_id
                    ),
                    "selection_id": self.selection_id,
                },
            ),
        )


class CanonicalAssetDecisionPreviewActionizer(
    DataObjectActionizer[
        CanonicalAssetDecisionPreviewRequest,
        CanonicalAssetDecisionPreviewResult,
    ]
):
    """Load fresh owner state and return one safe asset preview."""

    __slots__ = ("_loader",)

    def __init__(
        self, *, loader: CourseReferenceAuthorityLoadActionizer
    ) -> None:
        """Bind the single fresh owner-load capability."""
        if type(loader) is not CourseReferenceAuthorityLoadActionizer:
            raise TypeError("loader has an invalid type")
        self._loader = loader

    def action(
        self,
        *,
        request: CanonicalAssetDecisionPreviewRequest,
    ) -> CanonicalAssetDecisionPreviewResult:
        """Return the safe consequence projection of one fresh preview."""
        if type(request) is not CanonicalAssetDecisionPreviewRequest:
            raise TypeError("request has an invalid type")
        queue = self._loader.action(
            request=CourseReferenceAuthorityLoadRequest(
                scope=request.scope,
                selections=request.selections,
            )
        ).queue
        try:
            item = _queue_item(queue, request.selection_id)
            _require_expected_head(
                item.current_asset_decision,
                request.expected_current_decision_id,
            )
            if item.active_authority is None:
                raise CourseReferenceAuthorityError(
                    "asset preview lacks accepted identity"
                )
            plan = CanonicalAssetEvidencePlan(
                queue=queue,
                selection_id=request.selection_id,
                identity_state_projection_id=(
                    item.active_authority.state_projection_id
                ),
                assets=item.assets,
            )
            preview = CanonicalAssetDecisionPreview(
                plan=plan,
                disposition=request.disposition,
                competitor_dispositions=request.competitor_dispositions,
                expected_current_decision_id=(
                    request.expected_current_decision_id
                ),
            )
        except (CourseReferenceAuthorityError, TypeError) as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION,
                "asset preview is not available",
            ) from error
        return CanonicalAssetDecisionPreviewResult(
            request_id=request.request_id,
            preview_id=preview.preview_id,
            plan_id=preview.plan.plan_id,
            selection_id=preview.plan.selection_id,
            disposition=preview.disposition,
            competitor_dispositions=preview.competitor_dispositions,
            selected_asset_observation_id=preview.selected_asset_observation_id,
            expected_current_decision_id=preview.expected_current_decision_id,
            identity_state_projection_id=preview.plan.identity_state_projection_id,
            queue_id=preview.plan.queue.queue_id,
            item_revision_id=item.item_revision_id,
        )


_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")


def _content_id(value: str, *, field: str) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if type(value) is not str or _CONTENT_ID.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} is not a content ID")
    return value


def _stable_id(kind: str, payload: object) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    kind
        Typed input governed by the function annotation.
    payload
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    encoded = json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_default(value: object) -> object:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: getattr(value, item.name)
            for item in value.__dataclass_fields__.values()
            if item.init
        }
    raise TypeError(f"unsupported identity value: {type(value).__name__}")


def _require_expected_head(
    current: CurrentReviewDecisionHead | None,
    expected: str | None,
) -> None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    current
        Typed input governed by the function annotation.
    expected
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    actual = None if current is None else current.decision_id
    if actual != expected:
        raise CourseReferenceAuthorityError("decision stream revision is stale")


def _queue_item(
    queue: CourseReferenceAuthorityQueue,
    selection_id: str,
) -> CourseReferenceAuthorityQueueItem:
    """Return one exact queue item or fail closed.

    Parameters
    ----------
    queue
        Immutable queue searched without mutation.
    selection_id
        Exact Courses-owned selection identity.

    Returns
    -------
    CourseReferenceAuthorityQueueItem
        Matching immutable queue item.
    """
    for item in queue.items:
        if item.selection.selection_id == selection_id:
            return item
    raise CourseReferenceAuthorityError("selection is not in the queue")
