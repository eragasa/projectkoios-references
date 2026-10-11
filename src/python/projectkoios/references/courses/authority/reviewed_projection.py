"""Complete Courses-order reviewed reference projection."""

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
    DataObjectModel,
)
from projectkoios.references.identity import (
    ReferenceCandidate,
)
from projectkoios.references.path_safety import validate_citekey

from .errors import CourseReferenceAuthorityError
from .queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceItemResolution,
)
from .scope import (
    CourseDisplayCitekeyStatus,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedCourseReferenceBinding(DataObjectModel):
    """Compose one Courses locator binding with References authority."""

    scope_id: str
    selection_id: str
    locator_binding_id: str
    ordinal: int
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus
    reference_locator: str
    candidate_id: str
    bibliographic_work_id: str
    accepted_citekey: str
    source_asset_id: str
    identity_decision_id: str
    canonical_asset_decision_id: str
    state_projection_id: str
    authority_binding_id: str
    reviewed_binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        for label, value in (
            ("scope_id", self.scope_id),
            ("selection_id", self.selection_id),
            ("locator_binding_id", self.locator_binding_id),
            ("reference_locator", self.reference_locator),
            ("candidate_id", self.candidate_id),
            ("bibliographic_work_id", self.bibliographic_work_id),
            ("source_asset_id", self.source_asset_id),
            ("identity_decision_id", self.identity_decision_id),
            (
                "canonical_asset_decision_id",
                self.canonical_asset_decision_id,
            ),
            ("state_projection_id", self.state_projection_id),
            ("authority_binding_id", self.authority_binding_id),
        ):
            _content_id(value, field=label)
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise CourseReferenceAuthorityError("binding ordinal is invalid")
        validate_citekey(self.display_citekey, field="display citekey")
        validate_citekey(self.accepted_citekey, field="accepted citekey")
        if not isinstance(
            self.display_citekey_status,
            CourseDisplayCitekeyStatus,
        ):
            raise TypeError("display citekey status is invalid")
        object.__setattr__(
            self,
            "reviewed_binding_id",
            _stable_id(
                "reviewed-course-reference-binding",
                {
                    "accepted_citekey": self.accepted_citekey,
                    "authority_binding_id": self.authority_binding_id,
                    "bibliographic_work_id": self.bibliographic_work_id,
                    "candidate_id": self.candidate_id,
                    "canonical_asset_decision_id": (
                        self.canonical_asset_decision_id
                    ),
                    "display_citekey": self.display_citekey,
                    "display_citekey_status": self.display_citekey_status,
                    "identity_decision_id": self.identity_decision_id,
                    "locator_binding_id": self.locator_binding_id,
                    "ordinal": self.ordinal,
                    "reference_locator": self.reference_locator,
                    "scope_id": self.scope_id,
                    "selection_id": self.selection_id,
                    "source_asset_id": self.source_asset_id,
                    "state_projection_id": self.state_projection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedCourseReferenceProjection(DataObjectActionResult):
    """Return the ordered reviewed tuple for API/Courses composition."""

    queue_id: str
    scope_id: str
    course_id: str
    bindings: tuple[ReviewedCourseReferenceBinding, ...]
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.queue_id, field="queue_id")
        _content_id(self.scope_id, field="scope_id")
        _bounded(self.course_id, field="course_id")
        if not isinstance(self.bindings, tuple) or any(
            type(item) is not ReviewedCourseReferenceBinding
            for item in self.bindings
        ):
            raise TypeError("bindings must be an exact typed tuple")
        if not self.bindings:
            raise CourseReferenceAuthorityError("bindings must be non-empty")
        if tuple(item.ordinal for item in self.bindings) != tuple(
            range(1, len(self.bindings) + 1)
        ):
            raise CourseReferenceAuthorityError(
                "reviewed bindings must preserve exact Courses order"
            )
        if any(item.scope_id != self.scope_id for item in self.bindings):
            raise CourseReferenceAuthorityError(
                "reviewed binding scope differs from its projection"
            )
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "reviewed-course-reference-projection",
                {
                    "binding_ids": tuple(
                        item.reviewed_binding_id for item in self.bindings
                    ),
                    "course_id": self.course_id,
                    "queue_id": self.queue_id,
                    "scope_id": self.scope_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedCourseReferenceProjectionRequest(DataObjectActionRequest):
    """Request the complete Courses-order reviewed projection."""

    queue: CourseReferenceAuthorityQueue
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("queue has an invalid type")
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "reviewed-course-reference-projection-request",
                {"queue_id": self.queue.queue_id},
            ),
        )


class ReviewedCourseReferenceProjectionActionizer(
    DataObjectActionizer[
        ReviewedCourseReferenceProjectionRequest,
        ReviewedCourseReferenceProjection,
    ]
):
    """Compose an exact tuple only when every item has both review stages."""

    __slots__ = ()

    def action(
        self,
        *,
        request: ReviewedCourseReferenceProjectionRequest,
    ) -> ReviewedCourseReferenceProjection:
        """Execute the typed action and return its immutable result.

        Parameters
        ----------
        request
            Typed input governed by the function annotation.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(request) is not ReviewedCourseReferenceProjectionRequest:
            raise TypeError("request has an invalid type")
        queue = request.queue
        bindings = []
        for item in queue.items:
            candidate = _ready_candidate(item)
            authority = item.active_authority
            if authority is None or authority.source_asset_id is None:
                raise CourseReferenceAuthorityError(
                    "course reference scope is not completely reviewed"
                )
            assert authority.canonical_asset_decision_id is not None
            assert authority.authority_binding_id is not None
            bindings.append(
                ReviewedCourseReferenceBinding(
                    scope_id=item.selection.scope_id,
                    selection_id=item.selection.selection_id,
                    locator_binding_id=item.selection.locator_binding_id,
                    ordinal=item.selection.ordinal,
                    display_citekey=item.selection.display_citekey,
                    display_citekey_status=(
                        item.selection.display_citekey_status
                    ),
                    reference_locator=item.selection.reference_locator,
                    candidate_id=candidate.candidate_id,
                    bibliographic_work_id=authority.bibliographic_work_id,
                    accepted_citekey=authority.active_citekey,
                    source_asset_id=authority.source_asset_id,
                    identity_decision_id=authority.identity_decision_id,
                    canonical_asset_decision_id=(
                        authority.canonical_asset_decision_id
                    ),
                    state_projection_id=authority.state_projection_id,
                    authority_binding_id=authority.authority_binding_id,
                )
            )
        return ReviewedCourseReferenceProjection(
            queue_id=queue.queue_id,
            scope_id=queue.scope_id,
            course_id=queue.course_id,
            bindings=tuple(bindings),
        )


_MAX_TEXT = 4_096

_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")


def _bounded(value: str, *, field: str, maximum: int = _MAX_TEXT) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.
    maximum
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 0x20 for character in value)
    ):
        raise CourseReferenceAuthorityError(
            f"{field} must be bounded non-control text"
        )
    return value


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


def _ready_candidate(
    item: CourseReferenceAuthorityQueueItem,
) -> ReferenceCandidate:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    item
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if (
        item.resolution is not CourseReferenceItemResolution.READY
        or item.candidate is None
    ):
        raise CourseReferenceAuthorityError(
            "course reference item is unresolved and cannot mutate"
        )
    return item.candidate
