"""Typed identity consequence preview owner operation."""

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
from projectkoios.references.path_safety import validate_citekey
from projectkoios.references.review import (
    HumanReviewDimension,
    ReferenceIdentityDecision,
)

from .authority_state import (
    ActiveReferenceAuthority,
    CurrentReviewDecisionHead,
)
from .errors import CourseReferenceAuthorityError
from .plans import ReferenceIdentityDecisionPreview
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
class ReferenceIdentityDecisionPreviewRequest(DataObjectActionRequest):
    """Request one owner-generated identity consequence preview."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    disposition: ReferenceIdentityDecision
    target_state_projection_id: str | None
    canonical_citekey: str | None
    alias_citekeys: tuple[str, ...]
    selected_record_match_ids: tuple[str, ...]
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
        if not isinstance(self.disposition, ReferenceIdentityDecision):
            raise TypeError("identity disposition is invalid")
        if self.target_state_projection_id is not None:
            _content_id(
                self.target_state_projection_id,
                field="target_state_projection_id",
            )
        if self.canonical_citekey is not None:
            validate_citekey(
                self.canonical_citekey,
                field="canonical_citekey",
            )
        _citekeys(self.alias_citekeys, field="alias_citekeys")
        _content_ids(
            self.selected_record_match_ids,
            field="selected_record_match_ids",
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
                "reference-identity-decision-preview-request",
                {
                    "alias_citekeys": self.alias_citekeys,
                    "canonical_citekey": self.canonical_citekey,
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "scope_id": self.scope.scope_id,
                    "selected_record_match_ids": (
                        self.selected_record_match_ids
                    ),
                    "selection_ids": tuple(
                        item.selection_id for item in self.selections
                    ),
                    "selection_id": self.selection_id,
                    "target_state_projection_id": (
                        self.target_state_projection_id
                    ),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceIdentityDecisionPreviewResult(DataObjectActionResult):
    """Expose only the safe identity consequence and CAS identities."""

    request_id: str
    preview_id: str
    selection_id: str
    disposition: ReferenceIdentityDecision
    target_state_projection_id: str | None
    canonical_citekey: str | None
    alias_citekeys: tuple[str, ...]
    selected_record_match_ids: tuple[str, ...]
    expected_current_decision_id: str | None
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
            ("selection_id", self.selection_id),
            ("queue_id", self.queue_id),
            ("item_revision_id", self.item_revision_id),
        ):
            _content_id(value, field=label)
        if not isinstance(self.disposition, ReferenceIdentityDecision):
            raise TypeError("identity disposition is invalid")
        if self.target_state_projection_id is not None:
            _content_id(
                self.target_state_projection_id,
                field="target_state_projection_id",
            )
        if self.canonical_citekey is not None:
            validate_citekey(
                self.canonical_citekey,
                field="canonical_citekey",
            )
        _citekeys(self.alias_citekeys, field="alias_citekeys")
        _content_ids(
            self.selected_record_match_ids,
            field="selected_record_match_ids",
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
                "reference-identity-decision-preview-result",
                {
                    "alias_citekeys": self.alias_citekeys,
                    "canonical_citekey": self.canonical_citekey,
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "item_revision_id": self.item_revision_id,
                    "preview_id": self.preview_id,
                    "queue_id": self.queue_id,
                    "request_id": self.request_id,
                    "selected_record_match_ids": (
                        self.selected_record_match_ids
                    ),
                    "selection_id": self.selection_id,
                    "target_state_projection_id": (
                        self.target_state_projection_id
                    ),
                },
            ),
        )


class ReferenceIdentityDecisionPreviewActionizer(
    DataObjectActionizer[
        ReferenceIdentityDecisionPreviewRequest,
        ReferenceIdentityDecisionPreviewResult,
    ]
):
    """Load fresh owner state and return one safe identity preview."""

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
        request: ReferenceIdentityDecisionPreviewRequest,
    ) -> ReferenceIdentityDecisionPreviewResult:
        """Return the safe consequence projection of one fresh preview."""
        if type(request) is not ReferenceIdentityDecisionPreviewRequest:
            raise TypeError("request has an invalid type")
        queue = self._loader.action(
            request=CourseReferenceAuthorityLoadRequest(
                scope=request.scope,
                selections=request.selections,
            )
        ).queue
        try:
            item = _queue_item(queue, request.selection_id)
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.ITEM_NOT_FOUND,
                "course reference item is unavailable",
            ) from error
        if request.target_state_projection_id is not None:
            try:
                _target_authority(queue, request.target_state_projection_id)
            except CourseReferenceAuthorityError as error:
                raise CourseReferenceAuthorityServiceError(
                    CourseReferenceAuthorityFailureReason.TARGET_STALE,
                    "identity target is stale",
                ) from error
        context_id = (
            item.selection.course_id
            if request.disposition is ReferenceIdentityDecision.DEFER
            else _IDENTITY_CONTEXT
        )
        current = _current_decision(
            item.current_identity_decisions,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            context_id=context_id,
        )
        try:
            _require_expected_head(
                current, request.expected_current_decision_id
            )
            preview = ReferenceIdentityDecisionPreview(
                queue=queue,
                selection_id=request.selection_id,
                disposition=request.disposition,
                target_state_projection_id=request.target_state_projection_id,
                canonical_citekey=request.canonical_citekey,
                alias_citekeys=request.alias_citekeys,
                selected_record_match_ids=request.selected_record_match_ids,
                expected_current_decision_id=request.expected_current_decision_id,
            )
        except (CourseReferenceAuthorityError, TypeError) as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION,
                "identity preview is not available",
            ) from error
        return ReferenceIdentityDecisionPreviewResult(
            request_id=request.request_id,
            preview_id=preview.preview_id,
            selection_id=preview.selection_id,
            disposition=preview.disposition,
            target_state_projection_id=preview.target_state_projection_id,
            canonical_citekey=preview.canonical_citekey,
            alias_citekeys=preview.alias_citekeys,
            selected_record_match_ids=preview.selected_record_match_ids,
            expected_current_decision_id=preview.expected_current_decision_id,
            queue_id=preview.queue.queue_id,
            item_revision_id=item.item_revision_id,
        )


_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")

_IDENTITY_CONTEXT = "projectkoios.references.identity"


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


def _content_ids(
    values: tuple[str, ...],
    *,
    field: str,
    ordered: bool = False,
) -> None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    values
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.
    ordered
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    for value in values:
        _content_id(value, field=field)
    if len(values) != len(set(values)):
        raise CourseReferenceAuthorityError(f"{field} must be unique")
    if not ordered and values != tuple(sorted(values)):
        raise CourseReferenceAuthorityError(f"{field} must use lexical order")


def _citekeys(values: tuple[str, ...], *, field: str) -> None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    values
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    for value in values:
        validate_citekey(value, field=field)
    if values != tuple(sorted(set(values))):
        raise CourseReferenceAuthorityError(
            f"{field} must use unique lexical order"
        )


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


def _current_decision(
    decisions: tuple[CurrentReviewDecisionHead, ...],
    *,
    dimension: HumanReviewDimension,
    context_id: str,
) -> CurrentReviewDecisionHead | None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    decisions
        Typed input governed by the function annotation.
    dimension
        Typed input governed by the function annotation.
    context_id
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    matches = tuple(
        item
        for item in decisions
        if item.dimension is dimension and item.context_id == context_id
    )
    if len(matches) > 1:
        raise CourseReferenceAuthorityError(
            "decision stream has multiple current heads"
        )
    return matches[0] if matches else None


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


def _target_authority(
    queue: CourseReferenceAuthorityQueue,
    state_projection_id: str,
) -> ActiveReferenceAuthority:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    queue
        Typed input governed by the function annotation.
    state_projection_id
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    for item in queue.active_authorities:
        if item.state_projection_id == state_projection_id:
            return item
    raise CourseReferenceAuthorityError(
        "target is not an active accepted schema-5 projection"
    )
