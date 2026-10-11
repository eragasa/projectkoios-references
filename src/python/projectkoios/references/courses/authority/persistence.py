"""Append-only schema-5 authority transition persistence."""

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
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
    ReviewActorProvenance,
    ReviewTransitionKind,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
    StateClaim,
    StateKnowledge,
    StateRecordKind,
    candidate_state_claims,
    replay_reference_state,
)

from .authority_state import (
    ActiveReferenceAuthority,
    CurrentReviewDecisionHead,
)
from .contract import COURSE_REFERENCE_AUTHORITY_PRODUCER
from .errors import CourseReferenceAuthorityError
from .evidence import (
    ReferenceAssetAuthorityEvidence,
)
from .plans import (
    CanonicalAssetDecisionPreview,
    ReferenceIdentityDecisionPreview,
)
from .queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceItemResolution,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendReferenceIdentityDecisionRequest(DataObjectActionRequest):
    """Append exactly one owner-generated identity preview."""

    preview: ReferenceIdentityDecisionPreview
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    idempotency_evidence_ids: tuple[str, ...] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.preview) is not ReferenceIdentityDecisionPreview:
            raise TypeError("preview has an invalid type")
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor must be ReviewActorProvenance")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        _content_ids(
            self.idempotency_evidence_ids,
            field="idempotency_evidence_ids",
        )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "append-reference-identity-decision-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "idempotency_evidence_ids": (self.idempotency_evidence_ids),
                    "preview_id": self.preview.preview_id,
                    "rationale": self.rationale,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendCanonicalAssetDecisionRequest(DataObjectActionRequest):
    """Append exactly one owner-generated complete asset preview."""

    preview: CanonicalAssetDecisionPreview
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    idempotency_evidence_ids: tuple[str, ...] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.preview) is not CanonicalAssetDecisionPreview:
            raise TypeError("preview has an invalid type")
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor must be ReviewActorProvenance")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        _content_ids(
            self.idempotency_evidence_ids,
            field="idempotency_evidence_ids",
        )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "append-canonical-asset-decision-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "idempotency_evidence_ids": (self.idempotency_evidence_ids),
                    "preview_id": self.preview.preview_id,
                    "rationale": self.rationale,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityDecisionResult(DataObjectActionResult):
    """Report one appended decision and its optional accepted projection."""

    request_id: str
    decision: HumanReviewDecision
    state_projection: ReferenceStateProjection | None
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.request_id, field="request_id")
        if type(self.decision) is not HumanReviewDecision:
            raise TypeError("decision must be HumanReviewDecision")
        if (
            self.state_projection is not None
            and type(self.state_projection) is not ReferenceStateProjection
        ):
            raise TypeError("state_projection has an invalid type")
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "reference-authority-decision-result",
                {
                    "decision_id": self.decision.decision_id,
                    "request_id": self.request_id,
                    "state_projection_id": (
                        None
                        if self.state_projection is None
                        else self.state_projection.projection_id
                    ),
                },
            ),
        )


class ReferenceIdentityDecisionAppendActionizer(
    DataObjectActionizer[
        AppendReferenceIdentityDecisionRequest,
        ReferenceAuthorityDecisionResult,
    ]
):
    """Append one identity decision through the schema-5 CAS boundary."""

    __slots__ = ("_candidates", "_catalog", "_observations")

    def __init__(
        self,
        *,
        catalog: ReferenceCatalog,
        candidates: tuple[ReferenceCandidate, ...],
        observations: tuple[SourceBibliographyObservation, ...],
    ) -> None:
        """Bind immutable owner evidence and the schema-5 catalog capability."""
        if type(catalog) is not ReferenceCatalog:
            raise TypeError("catalog must be a ReferenceCatalog")
        if not isinstance(candidates, tuple) or any(
            type(item) is not ReferenceCandidate for item in candidates
        ):
            raise TypeError("candidates must be an exact typed tuple")
        if not isinstance(observations, tuple) or any(
            type(item) is not SourceBibliographyObservation
            for item in observations
        ):
            raise TypeError("observations must be an exact typed tuple")
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise CourseReferenceAuthorityError("candidate identities repeat")
        if len({item.observation_id for item in observations}) != len(
            observations
        ):
            raise CourseReferenceAuthorityError(
                "source observation identities repeat"
            )
        self._catalog = catalog
        self._candidates = candidates
        self._observations = observations

    def action(
        self, *, request: AppendReferenceIdentityDecisionRequest
    ) -> ReferenceAuthorityDecisionResult:
        """Append exactly one fresh explicit identity preview."""
        if type(request) is not AppendReferenceIdentityDecisionRequest:
            raise TypeError("request has an invalid identity request type")
        preview = request.preview
        queue = preview.queue
        item = _queue_item(queue, preview.selection_id)
        candidate = _candidate(
            self._candidates, _ready_candidate(item).candidate_id
        )
        assert item.rendered_entry is not None
        context = (
            item.selection.course_id
            if preview.disposition is ReferenceIdentityDecision.DEFER
            else _IDENTITY_CONTEXT
        )
        current = _current_decision(
            item.current_identity_decisions,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            context_id=context,
        )
        _require_expected_head(current, preview.expected_current_decision_id)
        target = (
            None
            if preview.target_state_projection_id is None
            else _target_authority(
                queue,
                preview.target_state_projection_id,
            )
        )
        evidence_ids = {
            queue.queue_id,
            queue.review_projection_id,
            preview.preview_id,
            request.request_id,
            *request.idempotency_evidence_ids,
            item.item_revision_id,
            item.selection.scope_id,
            item.selection.selection_id,
            item.selection.locator_binding_id,
            item.rendered_entry.entry_id,
            candidate.candidate_id,
            request.actor.verification_record_id,
            *(entry.observation_id for entry in item.observations),
            *preview.selected_record_match_ids,
        }
        if target is not None:
            evidence_ids.update(
                {
                    target.state_projection_id,
                    target.bibliographic_work_id,
                    target.identity_decision_id,
                }
            )
        decision = HumanReviewDecision.create(
            subject_id=candidate.candidate_id,
            context_id=context,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            decision=preview.disposition,
            producer=COURSE_REFERENCE_AUTHORITY_PRODUCER,
            transition_kind=(
                ReviewTransitionKind.INITIAL
                if current is None
                else ReviewTransitionKind.SUPERSESSION
            ),
            actor=request.actor,
            evidence_ids=tuple(sorted(evidence_ids)),
            rationale=request.rationale,
            decided_at=request.decided_at,
            supersedes_decision_id=(
                None if current is None else current.decision_id
            ),
        )
        state_projection = None
        if preview.disposition in {
            ReferenceIdentityDecision.ACCEPT_NEW,
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }:
            assert preview.canonical_citekey is not None
            state_projection = _identity_state_projection(
                candidate=candidate,
                decision=decision,
                disposition=preview.disposition,
                target=target,
                canonical_citekey=preview.canonical_citekey,
                alias_citekeys=preview.alias_citekeys,
            )
        self._catalog.append_course_authority_decision(
            candidate=candidate,
            observations=_candidate_observations(self._observations, candidate),
            decision=decision,
            state_projection=state_projection,
            expected_current_decision_id=preview.expected_current_decision_id,
            expected_queue_id=queue.queue_id,
            expected_item_revision_id=item.item_revision_id,
            expected_preview_id=preview.preview_id,
            expected_asset_plan_id=None,
            expected_review_projection_id=queue.review_projection_id,
            expected_state_projection_ids=queue.state_projection_ids,
            expected_asset_observation_ids=tuple(
                item.asset_observation_id for item in item.assets
            ),
        )
        return ReferenceAuthorityDecisionResult(
            request_id=request.request_id,
            decision=decision,
            state_projection=state_projection,
        )


class CanonicalAssetDecisionAppendActionizer(
    DataObjectActionizer[
        AppendCanonicalAssetDecisionRequest,
        ReferenceAuthorityDecisionResult,
    ]
):
    """Append one canonical-asset decision through schema-5 CAS."""

    __slots__ = ("_candidates", "_catalog", "_observations")

    def __init__(
        self,
        *,
        catalog: ReferenceCatalog,
        candidates: tuple[ReferenceCandidate, ...],
        observations: tuple[SourceBibliographyObservation, ...],
    ) -> None:
        """Bind immutable owner evidence and the schema-5 catalog capability."""
        if type(catalog) is not ReferenceCatalog:
            raise TypeError("catalog must be a ReferenceCatalog")
        if not isinstance(candidates, tuple) or any(
            type(item) is not ReferenceCandidate for item in candidates
        ):
            raise TypeError("candidates must be an exact typed tuple")
        if not isinstance(observations, tuple) or any(
            type(item) is not SourceBibliographyObservation
            for item in observations
        ):
            raise TypeError("observations must be an exact typed tuple")
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise CourseReferenceAuthorityError("candidate identities repeat")
        if len({item.observation_id for item in observations}) != len(
            observations
        ):
            raise CourseReferenceAuthorityError(
                "source observation identities repeat"
            )
        self._catalog = catalog
        self._candidates = candidates
        self._observations = observations

    def action(
        self, *, request: AppendCanonicalAssetDecisionRequest
    ) -> ReferenceAuthorityDecisionResult:
        """Append exactly one fresh complete asset preview."""
        if type(request) is not AppendCanonicalAssetDecisionRequest:
            raise TypeError("request has an invalid asset request type")
        preview = request.preview
        plan = preview.plan
        queue = plan.queue
        item = _queue_item(queue, plan.selection_id)
        candidate = _candidate(
            self._candidates, _ready_candidate(item).candidate_id
        )
        if item.active_authority is None:
            raise CourseReferenceAuthorityError(
                "asset decision requires accepted identity authority"
            )
        current = item.current_asset_decision
        _require_expected_head(current, preview.expected_current_decision_id)
        selected = (
            None
            if preview.selected_asset_observation_id is None
            else _asset(item, preview.selected_asset_observation_id)
        )
        evidence_ids = {
            queue.queue_id,
            queue.review_projection_id,
            plan.plan_id,
            request.request_id,
            *request.idempotency_evidence_ids,
            preview.preview_id,
            item.item_revision_id,
            item.selection.scope_id,
            item.selection.selection_id,
            candidate.candidate_id,
            item.active_authority.state_projection_id,
            item.active_authority.bibliographic_work_id,
            item.active_authority.identity_decision_id,
            request.actor.verification_record_id,
            *(asset.asset_observation_id for asset in item.assets),
        }
        if selected is not None:
            evidence_ids.update(_asset_evidence_ids(selected))
        decision = HumanReviewDecision.create(
            subject_id=candidate.candidate_id,
            context_id=_ASSET_CONTEXT,
            dimension=HumanReviewDimension.CANONICAL_ASSET,
            decision=preview.disposition,
            producer=COURSE_REFERENCE_AUTHORITY_PRODUCER,
            transition_kind=(
                ReviewTransitionKind.INITIAL
                if current is None
                else ReviewTransitionKind.SUPERSESSION
            ),
            actor=request.actor,
            evidence_ids=tuple(sorted(evidence_ids)),
            rationale=request.rationale,
            decided_at=request.decided_at,
            supersedes_decision_id=(
                None if current is None else current.decision_id
            ),
        )
        state_projection = None
        if preview.disposition is CanonicalAssetDecision.AUTHORIZE:
            assert selected is not None
            identity_decision = _accepted_identity_decision(item)
            state_projection = _asset_state_projection(
                candidate=candidate,
                identity_decision=identity_decision,
                authority=item.active_authority,
                asset_decision=decision,
                asset=selected,
            )
        self._catalog.append_course_authority_decision(
            candidate=candidate,
            observations=_candidate_observations(self._observations, candidate),
            decision=decision,
            state_projection=state_projection,
            expected_current_decision_id=preview.expected_current_decision_id,
            expected_queue_id=queue.queue_id,
            expected_item_revision_id=item.item_revision_id,
            expected_preview_id=preview.preview_id,
            expected_asset_plan_id=plan.plan_id,
            expected_review_projection_id=queue.review_projection_id,
            expected_state_projection_ids=queue.state_projection_ids,
            expected_asset_observation_ids=tuple(
                item.asset_observation_id for item in item.assets
            ),
        )
        return ReferenceAuthorityDecisionResult(
            request_id=request.request_id,
            decision=decision,
            state_projection=state_projection,
        )


def _candidate(
    candidates: tuple[ReferenceCandidate, ...],
    candidate_id: str,
) -> ReferenceCandidate:
    """Return exact candidate evidence from an immutable inventory."""
    for candidate in candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    raise CourseReferenceAuthorityError(
        "appender lacks exact candidate evidence"
    )


def _candidate_observations(
    observations: tuple[SourceBibliographyObservation, ...],
    candidate: ReferenceCandidate,
) -> tuple[SourceBibliographyObservation, ...]:
    """Return the candidate's exact ordered source observations."""
    by_id = {item.observation_id: item for item in observations}
    try:
        return tuple(by_id[item] for item in candidate.source_observation_ids)
    except KeyError as error:
        raise CourseReferenceAuthorityError(
            "appender lacks exact source observation evidence"
        ) from error


def _identity_state_projection(
    *,
    candidate: ReferenceCandidate,
    decision: HumanReviewDecision,
    disposition: ReferenceIdentityDecision,
    target: ActiveReferenceAuthority | None,
    canonical_citekey: str,
    alias_citekeys: tuple[str, ...],
) -> ReferenceStateProjection:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    candidate
        Typed input governed by the function annotation.
    decision
        Typed input governed by the function annotation.
    disposition
        Typed input governed by the function annotation.
    target
        Typed input governed by the function annotation.
    canonical_citekey
        Typed input governed by the function annotation.
    alias_citekeys
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if disposition is ReferenceIdentityDecision.ACCEPT_NEW:
        work_id = _stable_id(
            "bibliographic-work",
            {
                "candidate_id": candidate.candidate_id,
                "creating_decision_id": decision.decision_id,
            },
        )
        active_citekey = canonical_citekey
        aliases = alias_citekeys
    else:
        if target is None:
            raise CourseReferenceAuthorityError(
                "accepted existing or merged identity requires a target"
            )
        work_id = target.bibliographic_work_id
        active_citekey = canonical_citekey
        aliases = alias_citekeys
    claims = _candidate_claims_for_acceptance(candidate)
    claims.extend(
        _human_claims(
            decision=decision,
            values=(
                ("identity_status", "accepted"),
                ("bibliographic_work_id", work_id),
                ("active_citekey", active_citekey),
                ("alias_citekeys", aliases),
                ("identity_decision_id", decision.decision_id),
            ),
        )
    )
    authoritative_ids = {
        candidate.candidate_id,
        decision.decision_id,
        *decision.evidence_ids,
    }
    return replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=claims,
        authoritative_input_ids=tuple(sorted(authoritative_ids)),
        exclusions=(
            "canonical asset requires a separate curator decision",
            "claim support is not projected by references",
            "publication is not projected by references",
            "rights clearance is not granted by identity acceptance",
        ),
    )


def _asset_state_projection(
    *,
    candidate: ReferenceCandidate,
    identity_decision: CurrentReviewDecisionHead,
    authority: ActiveReferenceAuthority,
    asset_decision: HumanReviewDecision,
    asset: ReferenceAssetAuthorityEvidence,
) -> ReferenceStateProjection:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    candidate
        Typed input governed by the function annotation.
    identity_decision
        Typed input governed by the function annotation.
    authority
        Typed input governed by the function annotation.
    asset_decision
        Typed input governed by the function annotation.
    asset
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    source_asset_id = _stable_id(
        "source-asset",
        {
            "asset_observation_id": asset.asset_observation_id,
            "authorization_decision_id": asset_decision.decision_id,
            "bibliographic_work_id": authority.bibliographic_work_id,
        },
    )
    binding_id = _stable_id(
        "reference-source-asset-binding",
        {
            "asset_observation_id": asset.asset_observation_id,
            "bibliographic_work_id": authority.bibliographic_work_id,
            "candidate_id": candidate.candidate_id,
            "canonical_asset_decision_id": asset_decision.decision_id,
            "identity_decision_id": authority.identity_decision_id,
            "source_asset_id": source_asset_id,
        },
    )
    claims = _candidate_claims_for_acceptance(candidate)
    claims.extend(
        _human_claims(
            decision=identity_decision,
            values=(
                ("identity_status", "accepted"),
                (
                    "bibliographic_work_id",
                    authority.bibliographic_work_id,
                ),
                ("active_citekey", authority.active_citekey),
                ("alias_citekeys", authority.alias_citekeys),
                ("identity_decision_id", authority.identity_decision_id),
            ),
        )
    )
    claims.extend(
        _human_claims(
            decision=asset_decision,
            values=(
                ("source_asset_id", source_asset_id),
                (
                    "canonical_asset_decision_id",
                    asset_decision.decision_id,
                ),
                ("authority_binding_id", binding_id),
            ),
        )
    )
    authoritative_ids = {
        candidate.candidate_id,
        identity_decision.decision_id,
        asset_decision.decision_id,
        *asset_decision.evidence_ids,
    }
    return replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=claims,
        authoritative_input_ids=tuple(sorted(authoritative_ids)),
        exclusions=(
            "asset authorization establishes linkage, not rights clearance",
            "claim support is not projected by references",
            "publication is not projected by references",
        ),
    )


def _candidate_claims_for_acceptance(
    candidate: ReferenceCandidate,
) -> list[StateClaim]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    candidate
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    return [
        item
        for item in candidate_state_claims(candidate)
        if item.field != "identity_status"
    ]


def _human_claims(
    *,
    decision: HumanReviewDecision | CurrentReviewDecisionHead,
    values: tuple[tuple[str, object], ...],
) -> list[StateClaim]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    decision
        Typed input governed by the function annotation.
    values
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    actor_id = (
        decision.actor.actor_id
        if isinstance(decision, HumanReviewDecision)
        else decision.actor_id
    )
    authority_scope = (
        decision.actor.authority_scope.value
        if isinstance(decision, HumanReviewDecision)
        else decision.authority_scope
    )
    verification_record_id = (
        decision.actor.verification_record_id
        if isinstance(decision, HumanReviewDecision)
        else decision.actor_verification_record_id
    )
    return [
        StateClaim(
            subject_id=decision.subject_id,
            field=name,
            knowledge=StateKnowledge.OBSERVED,
            value_json=_canonical_json(value),
            record_kind=StateRecordKind.HUMAN_DECISION,
            authority_owner="projectkoios-references",
            authoritative_input_id=decision.decision_id,
            source_locator=(
                f"course-reference-authority/{decision.dimension.value}/{name}"
            ),
            actor_id=actor_id,
            authority_scope=authority_scope,
            actor_verification_record_id=verification_record_id,
        )
        for name, value in values
    ]


_MAX_TEXT = 4_096

_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")

_IDENTITY_CONTEXT = "projectkoios.references.identity"

_ASSET_CONTEXT = "projectkoios.references.canonical-asset"


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


def _canonical_json(value: object) -> str:
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
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
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


def _accepted_identity_decision(
    item: CourseReferenceAuthorityQueueItem,
) -> CurrentReviewDecisionHead:
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
    if item.active_authority is None:
        raise CourseReferenceAuthorityError("candidate is not accepted")
    for decision in item.current_identity_decisions:
        if decision.decision_id == item.active_authority.identity_decision_id:
            return decision
    raise CourseReferenceAuthorityError(
        "accepted state lacks its current identity decision"
    )


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


def _asset_evidence_ids(
    asset: ReferenceAssetAuthorityEvidence,
) -> tuple[str, ...]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    asset
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    values = {
        asset.asset_observation_id,
        *asset.document_binding_ids,
        *asset.ingestion_evidence_ids,
        *(link.link_id for link in asset.ingestion_artifact_links),
    }
    if asset.runtime_evidence_id is not None:
        values.add(asset.runtime_evidence_id)
    return tuple(sorted(values))


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
