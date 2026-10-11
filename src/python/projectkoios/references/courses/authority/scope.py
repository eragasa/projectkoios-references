"""Courses-owned selection and scope evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, is_dataclass
from enum import Enum, StrEnum

from projectkoios.base import (
    DataObjectModel,
)
from projectkoios.references.path_safety import validate_citekey

from .errors import CourseReferenceAuthorityError


class CourseReferenceSelectionOrigin(StrEnum):
    """Mirror the Courses-owned selection origin."""

    PRESERVED_MANUSCRIPT = "preserved-manuscript"
    DIRECTED_REFERENCE_SCOPE = "directed-reference-scope"


class CourseReferenceRole(StrEnum):
    """Mirror the bounded Courses-owned reference role."""

    MANUSCRIPT_BIBLIOGRAPHY = "manuscript-bibliography"


class CourseDisplayCitekeyStatus(StrEnum):
    """Mirror the two non-authoritative Courses display statuses."""

    OBSERVED = "observed"
    PROPOSED_NONCANONICAL = "proposed-noncanonical"


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectionEvidence(DataObjectModel):
    """Mirror one Courses-owned selection without deriving its identity."""

    scope_id: str
    selection_id: str
    locator_binding_id: str
    course_id: str
    manifest_id: str
    inventory_id: str
    ordinal: int
    origin: CourseReferenceSelectionOrigin
    role: CourseReferenceRole
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus
    reference_locator: str

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
        ):
            _content_id(value, field=label)
        _bounded(self.course_id, field="course_id")
        _content_id(self.manifest_id, field="manifest_id")
        _content_id(self.inventory_id, field="inventory_id")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= _MAX_ITEMS:
            raise CourseReferenceAuthorityError(
                "selection ordinal is outside the supported range"
            )
        if not isinstance(self.origin, CourseReferenceSelectionOrigin):
            raise TypeError("origin must be CourseReferenceSelectionOrigin")
        if self.role is not CourseReferenceRole.MANUSCRIPT_BIBLIOGRAPHY:
            raise CourseReferenceAuthorityError(
                "selection role must be manuscript-bibliography"
            )
        validate_citekey(self.display_citekey, field="display citekey")
        if not isinstance(
            self.display_citekey_status,
            CourseDisplayCitekeyStatus,
        ):
            raise TypeError(
                "display_citekey_status must be CourseDisplayCitekeyStatus"
            )
        _content_id(self.reference_locator, field="reference_locator")
        expected_binding_id = _stable_id(
            "course-reference-locator-binding",
            {
                "contract_version": "1.0",
                "display_citekey": self.display_citekey,
                "display_citekey_status": self.display_citekey_status,
                "ordinal": self.ordinal,
                "reference_locator": self.reference_locator,
                "reference_owner": "projectkoios-references",
            },
        )
        if self.locator_binding_id != expected_binding_id:
            raise CourseReferenceAuthorityError(
                "locator binding differs from the Courses contract"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceResolutionScopeEvidence(DataObjectModel):
    """Mirror the complete Courses 1.0 resolution-scope envelope."""

    scope_id: str
    course_id: str
    course_title: str
    manifest_id: str
    manifest_sha256: str
    inventory_id: str
    total: int
    ordered_selection_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.scope_id, field="scope_id")
        _bounded(self.course_id, field="course_id")
        _bounded(self.course_title, field="course_title", maximum=500)
        _content_id(self.manifest_id, field="manifest_id")
        _sha256(self.manifest_sha256, field="manifest_sha256")
        _content_id(self.inventory_id, field="inventory_id")
        if (
            type(self.total) is not int
            or not 1 <= self.total <= _MAX_ITEMS
            or self.total != len(self.ordered_selection_ids)
        ):
            raise CourseReferenceAuthorityError(
                "scope total differs from its ordered selection inventory"
            )
        _content_ids(
            self.ordered_selection_ids,
            field="ordered_selection_ids",
            ordered=True,
        )


_MAX_ITEMS = 10_000

_MAX_TEXT = 4_096

_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")

_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _sha256(value: str, *, field: str) -> str:
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
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} is not SHA-256")
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
