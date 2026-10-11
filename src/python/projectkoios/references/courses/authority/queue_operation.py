"""Typed queue loading owner operation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, is_dataclass
from enum import Enum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
)

from .queue import (
    CourseReferenceAuthorityQueue,
)
from .scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)
from .service import (
    CourseReferenceAuthorityLoadActionizer,
    CourseReferenceAuthorityLoadRequest,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueueLoadRequest(DataObjectActionRequest):
    """Request the current owner-loaded course authority queue."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
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
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "course-reference-authority-queue-load-request",
                {
                    "scope_id": self.scope.scope_id,
                    "selection_ids": tuple(
                        item.selection_id for item in self.selections
                    ),
                },
            ),
        )


class CourseReferenceAuthorityQueueLoadActionizer(
    DataObjectActionizer[
        CourseReferenceAuthorityQueueLoadRequest,
        CourseReferenceAuthorityQueue,
    ]
):
    """Load and return the current owner-composed course authority queue."""

    __slots__ = ("_loader",)

    def __init__(
        self,
        *,
        loader: CourseReferenceAuthorityLoadActionizer,
    ) -> None:
        """Bind the single fresh owner-load capability."""
        if type(loader) is not CourseReferenceAuthorityLoadActionizer:
            raise TypeError("loader has an invalid type")
        self._loader = loader

    def action(
        self,
        *,
        request: CourseReferenceAuthorityQueueLoadRequest,
    ) -> CourseReferenceAuthorityQueue:
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
        if type(request) is not CourseReferenceAuthorityQueueLoadRequest:
            raise TypeError("request has an invalid type")
        return self._loader.action(
            request=CourseReferenceAuthorityLoadRequest(
                scope=request.scope,
                selections=request.selections,
            )
        ).queue


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
