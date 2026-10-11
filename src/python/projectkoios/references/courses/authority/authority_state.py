"""Accepted References authority and decision-head value contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from projectkoios.base import (
    DataObjectModel,
)
from projectkoios.references.path_safety import validate_citekey
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
)

from .errors import CourseReferenceAuthorityError


@dataclass(frozen=True, slots=True, kw_only=True)
class ActiveReferenceAuthority(DataObjectModel):
    """Path-free active identity and optional source-asset authority."""

    candidate_id: str
    state_projection_id: str
    bibliographic_work_id: str
    active_citekey: str
    alias_citekeys: tuple[str, ...]
    identity_decision_id: str
    source_asset_id: str | None
    canonical_asset_decision_id: str | None
    authority_binding_id: str | None

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        for label, value in (
            ("candidate_id", self.candidate_id),
            ("state_projection_id", self.state_projection_id),
            ("bibliographic_work_id", self.bibliographic_work_id),
            ("identity_decision_id", self.identity_decision_id),
        ):
            _content_id(value, field=label)
        validate_citekey(self.active_citekey, field="active citekey")
        _citekeys(self.alias_citekeys, field="alias citekeys")
        if self.active_citekey in self.alias_citekeys:
            raise CourseReferenceAuthorityError(
                "active citekey cannot also be an alias"
            )
        optional = (
            self.source_asset_id,
            self.canonical_asset_decision_id,
            self.authority_binding_id,
        )
        if any(value is None for value in optional) and any(
            value is not None for value in optional
        ):
            raise CourseReferenceAuthorityError(
                "source-asset authority must be complete or absent"
            )
        for optional_value in optional:
            if optional_value is not None:
                _content_id(
                    optional_value,
                    field="source-asset authority identity",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentReviewDecisionHead(DataObjectModel):
    """Expose a decision head without rationale or private evidence details."""

    decision_id: str
    subject_id: str
    context_id: str
    dimension: HumanReviewDimension
    decision: str
    actor_id: str
    authority_scope: str
    actor_verification_record_id: str
    decided_at: str

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.decision_id, field="decision_id")
        _content_id(self.subject_id, field="subject_id")
        _bounded(self.context_id, field="context_id")
        if self.dimension not in {
            HumanReviewDimension.REFERENCE_IDENTITY,
            HumanReviewDimension.CANONICAL_ASSET,
        }:
            raise CourseReferenceAuthorityError(
                "queue decision head has an unsupported dimension"
            )
        allowed_decisions = {
            HumanReviewDimension.REFERENCE_IDENTITY: {
                item.value for item in ReferenceIdentityDecision
            },
            HumanReviewDimension.CANONICAL_ASSET: {
                item.value for item in CanonicalAssetDecision
            },
        }
        expected_scopes = {
            HumanReviewDimension.REFERENCE_IDENTITY: (
                "reference-identity-curator"
            ),
            HumanReviewDimension.CANONICAL_ASSET: ("canonical-asset-curator"),
        }
        if self.decision not in allowed_decisions[self.dimension]:
            raise CourseReferenceAuthorityError(
                "queue decision is invalid for its dimension"
            )
        _bounded(self.actor_id, field="actor_id")
        if "/" in self.actor_id or "\\" in self.actor_id:
            raise CourseReferenceAuthorityError(
                "queue actor ID cannot contain a filesystem separator"
            )
        if self.authority_scope != expected_scopes[self.dimension]:
            raise CourseReferenceAuthorityError(
                "queue decision has the wrong authority scope"
            )
        _content_id(
            self.actor_verification_record_id,
            field="actor_verification_record_id",
        )
        _bounded(self.decided_at, field="decided_at")


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
