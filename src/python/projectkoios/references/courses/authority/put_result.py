"""Safe immutable authority PUT result contract."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum

from projectkoios.base import (
    DataObjectActionResult,
)

from .errors import CourseReferenceAuthorityError


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityDecisionPutResult(DataObjectActionResult):
    """Expose a safe owner-reread result without the internal queue graph."""

    put_request_id: str
    decision_append_request_id: str
    decision_id: str
    state_projection_id: str | None
    preview_id: str
    receipt_id: str
    refreshed_queue_id: str
    refreshed_item_revision_id: str
    current_decision_id: str
    current_state_projection_id: str | None
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        for label, value in (
            ("put_request_id", self.put_request_id),
            (
                "decision_append_request_id",
                self.decision_append_request_id,
            ),
            ("decision_id", self.decision_id),
            ("preview_id", self.preview_id),
            ("receipt_id", self.receipt_id),
            ("refreshed_queue_id", self.refreshed_queue_id),
            (
                "refreshed_item_revision_id",
                self.refreshed_item_revision_id,
            ),
            ("current_decision_id", self.current_decision_id),
        ):
            _content_id(value, field=label)
        if self.state_projection_id is not None:
            _content_id(
                self.state_projection_id,
                field="state_projection_id",
            )
        if self.current_state_projection_id is not None:
            _content_id(
                self.current_state_projection_id,
                field="current_state_projection_id",
            )
        if self.decision_id != self.current_decision_id:
            raise CourseReferenceAuthorityError(
                "PUT result decision differs from owner reread"
            )
        if self.state_projection_id != self.current_state_projection_id:
            raise CourseReferenceAuthorityError(
                "PUT result projection differs from owner reread"
            )
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "reference-authority-decision-put-result",
                {
                    "current_decision_id": self.current_decision_id,
                    "current_state_projection_id": (
                        self.current_state_projection_id
                    ),
                    "decision_append_request_id": (
                        self.decision_append_request_id
                    ),
                    "decision_id": self.decision_id,
                    "preview_id": self.preview_id,
                    "put_request_id": self.put_request_id,
                    "receipt_id": self.receipt_id,
                    "refreshed_item_revision_id": (
                        self.refreshed_item_revision_id
                    ),
                    "refreshed_queue_id": self.refreshed_queue_id,
                    "state_projection_id": self.state_projection_id,
                },
            ),
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
