"""Immutable identity and canonical-asset consequence plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum

from projectkoios.base import (
    DataObjectModel,
)
from projectkoios.references.identity import (
    ReferenceCandidate,
)
from projectkoios.references.path_safety import validate_citekey
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
)

from .authority_state import (
    ActiveReferenceAuthority,
    CurrentReviewDecisionHead,
)
from .errors import CourseReferenceAuthorityError
from .evidence import (
    ReferenceAssetAuthorityEvidence,
    RuntimeAssetAvailability,
)
from .queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceItemResolution,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceIdentityDecisionPreview(DataObjectModel):
    """Owner-generated explicit identity action preview."""

    queue: CourseReferenceAuthorityQueue
    selection_id: str
    disposition: ReferenceIdentityDecision
    target_state_projection_id: str | None
    canonical_citekey: str | None
    alias_citekeys: tuple[str, ...]
    selected_record_match_ids: tuple[str, ...]
    expected_current_decision_id: str | None
    preview_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("queue has an invalid type")
        item = _queue_item(self.queue, self.selection_id)
        candidate = _ready_candidate(item)
        if self.disposition not in item.allowed_identity_actions:
            raise CourseReferenceAuthorityError(
                "identity disposition is not currently allowed"
            )
        _citekeys(self.alias_citekeys, field="alias_citekeys")
        _content_ids(
            self.selected_record_match_ids,
            field="selected_record_match_ids",
        )
        available_match_ids = {match.record_id for match in item.record_matches}
        if not set(self.selected_record_match_ids).issubset(
            available_match_ids
        ):
            raise CourseReferenceAuthorityError(
                "identity preview selects an unavailable record match"
            )
        accepting = self.disposition in {
            ReferenceIdentityDecision.ACCEPT_NEW,
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }
        if accepting != (self.canonical_citekey is not None):
            raise CourseReferenceAuthorityError(
                "canonical citekey does not match identity disposition"
            )
        if self.canonical_citekey is not None:
            validate_citekey(
                self.canonical_citekey,
                field="canonical citekey",
            )
            if self.canonical_citekey in self.alias_citekeys:
                raise CourseReferenceAuthorityError(
                    "canonical citekey cannot also be an alias"
                )
        needs_target = self.disposition in {
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }
        if needs_target != (self.target_state_projection_id is not None):
            raise CourseReferenceAuthorityError(
                "identity target does not match the disposition"
            )
        target = (
            None
            if self.target_state_projection_id is None
            else _target_authority(
                self.queue,
                self.target_state_projection_id,
            )
        )
        if self.disposition is ReferenceIdentityDecision.ACCEPT_NEW:
            if self.canonical_citekey != candidate.proposed_citekey:
                raise CourseReferenceAuthorityError(
                    "new work canonical citekey must be explicitly confirmed"
                )
            if self.alias_citekeys:
                raise CourseReferenceAuthorityError(
                    "new work cannot begin with inferred aliases"
                )
            if any(
                authority.active_citekey == self.canonical_citekey
                for authority in self.queue.active_authorities
            ):
                raise CourseReferenceAuthorityError(
                    "canonical citekey is already active"
                )
        elif target is not None:
            if (
                self.disposition is ReferenceIdentityDecision.ACCEPT_EXISTING
                and candidate.proposed_citekey != target.active_citekey
            ):
                raise CourseReferenceAuthorityError(
                    "existing-work target differs from the candidate key"
                )
            if self.canonical_citekey != target.active_citekey:
                raise CourseReferenceAuthorityError(
                    "canonical citekey differs from the explicit target"
                )
            expected_aliases = set(target.alias_citekeys)
            if (
                self.disposition is ReferenceIdentityDecision.MERGE
                and candidate.proposed_citekey != target.active_citekey
            ):
                expected_aliases.add(candidate.proposed_citekey)
            if self.alias_citekeys != tuple(sorted(expected_aliases)):
                raise CourseReferenceAuthorityError(
                    "explicit aliases differ from the target/merge plan"
                )
        elif self.alias_citekeys:
            raise CourseReferenceAuthorityError(
                "non-accepting identity preview cannot carry aliases"
            )
        context_id = (
            item.selection.course_id
            if self.disposition is ReferenceIdentityDecision.DEFER
            else _IDENTITY_CONTEXT
        )
        current = _current_decision(
            item.current_identity_decisions,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            context_id=context_id,
        )
        _require_expected_head(current, self.expected_current_decision_id)
        object.__setattr__(
            self,
            "preview_id",
            _stable_id(
                "reference-identity-decision-preview",
                {
                    "alias_citekeys": self.alias_citekeys,
                    "canonical_citekey": self.canonical_citekey,
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "item_revision_id": item.item_revision_id,
                    "queue_id": self.queue.queue_id,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetEvidencePlan(DataObjectModel):
    """Fresh post-identity plan binding all asset competitors and evidence."""

    queue: CourseReferenceAuthorityQueue
    selection_id: str
    identity_state_projection_id: str
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        item = _queue_item(self.queue, self.selection_id)
        _ready_candidate(item)
        if item.active_authority is None:
            raise CourseReferenceAuthorityError(
                "asset plan requires current accepted identity"
            )
        if (
            self.identity_state_projection_id
            != item.active_authority.state_projection_id
        ):
            raise CourseReferenceAuthorityError(
                "asset plan identity projection is stale"
            )
        if self.assets != item.assets:
            raise CourseReferenceAuthorityError(
                "asset plan differs from the refreshed queue evidence"
            )
        if not isinstance(self.assets, tuple) or any(
            type(item) is not ReferenceAssetAuthorityEvidence
            for item in self.assets
        ):
            raise TypeError("assets must be an exact typed tuple")
        object.__setattr__(
            self,
            "plan_id",
            _stable_id(
                "canonical-asset-evidence-plan",
                {
                    "asset_evidence": self.assets,
                    "identity_state_projection_id": (
                        self.identity_state_projection_id
                    ),
                    "item_revision_id": item.item_revision_id,
                    "queue_id": self.queue.queue_id,
                    "selection_id": self.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetCompetitorDisposition(DataObjectModel):
    """Record an explicit action and rationale for one plan competitor."""

    asset_observation_id: str
    disposition: CanonicalAssetDecision
    rationale: str

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(
            self.asset_observation_id,
            field="asset_observation_id",
        )
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("competitor disposition is invalid")
        _bounded(self.rationale, field="competitor rationale")


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetDecisionPreview(DataObjectModel):
    """Owner-generated asset decision preview over a complete fresh plan."""

    plan: CanonicalAssetEvidencePlan
    disposition: CanonicalAssetDecision
    competitor_dispositions: tuple[CanonicalAssetCompetitorDisposition, ...]
    expected_current_decision_id: str | None
    selected_asset_observation_id: str | None = field(init=False)
    preview_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.plan) is not CanonicalAssetEvidencePlan:
            raise TypeError("plan has an invalid type")
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("asset disposition is invalid")
        if not isinstance(self.competitor_dispositions, tuple) or any(
            type(item) is not CanonicalAssetCompetitorDisposition
            for item in self.competitor_dispositions
        ):
            raise TypeError(
                "competitor_dispositions must be an exact typed tuple"
            )
        asset_ids = tuple(
            item.asset_observation_id for item in self.plan.assets
        )
        disposition_ids = tuple(
            item.asset_observation_id for item in self.competitor_dispositions
        )
        if tuple(sorted(asset_ids)) != tuple(sorted(disposition_ids)):
            raise CourseReferenceAuthorityError(
                "asset preview must disposition every competitor exactly once"
            )
        selected = tuple(
            item
            for item in self.competitor_dispositions
            if item.disposition is CanonicalAssetDecision.AUTHORIZE
        )
        if self.disposition is CanonicalAssetDecision.AUTHORIZE:
            if len(selected) != 1:
                raise CourseReferenceAuthorityError(
                    "asset authorization must select exactly one competitor"
                )
            selected_asset = _asset(
                _queue_item(self.plan.queue, self.plan.selection_id),
                selected[0].asset_observation_id,
            )
            if selected_asset.runtime_availability is not (
                RuntimeAssetAvailability.AVAILABLE
            ):
                raise CourseReferenceAuthorityError(
                    "authorized asset is not freshly available"
                )
        elif selected:
            raise CourseReferenceAuthorityError(
                "non-authorization preview cannot authorize a competitor"
            )
        object.__setattr__(
            self,
            "selected_asset_observation_id",
            None if not selected else selected[0].asset_observation_id,
        )
        item = _queue_item(self.plan.queue, self.plan.selection_id)
        _require_expected_head(
            item.current_asset_decision,
            self.expected_current_decision_id,
        )
        object.__setattr__(
            self,
            "preview_id",
            _stable_id(
                "canonical-asset-decision-preview",
                {
                    "competitor_dispositions": (self.competitor_dispositions),
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "plan_id": self.plan.plan_id,
                },
            ),
        )


_MAX_TEXT = 4_096

_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")

_IDENTITY_CONTEXT = "projectkoios.references.identity"


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


def _asset(
    item: CourseReferenceAuthorityQueueItem,
    observation_id: str,
) -> ReferenceAssetAuthorityEvidence:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    item
        Typed input governed by the function annotation.
    observation_id
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    for asset in item.assets:
        if asset.asset_observation_id == observation_id:
            return asset
    raise CourseReferenceAuthorityError(
        "selected asset is not in the current candidate plan"
    )
