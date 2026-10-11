"""Courses-ordered left queue projection and validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, is_dataclass
from enum import Enum, StrEnum
from typing import cast

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyRenderedEntry,
    CandidateBibliographyRenderResult,
)
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
    ReviewProjection,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
)

from .authority_state import (
    ActiveReferenceAuthority,
    CurrentReviewDecisionHead,
)
from .contract import COURSE_REFERENCE_AUTHORITY_CONTRACT_ID
from .errors import CourseReferenceAuthorityError
from .evidence import (
    ObservedCandidateEntry,
    ReferenceAssetAuthorityEvidence,
    ReferenceRecordDiscrepancy,
    ReferenceRecordMatch,
    ReferenceRecordMatchKind,
    RenderedCandidateEntryEvidence,
    RenderedEntryCandidateBinding,
    RuntimeAssetAvailability,
)
from .scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)


class CourseReferenceItemResolution(StrEnum):
    """Expose left-projection resolution without dropping a Course item."""

    READY = "ready"
    RENDERED_LOCATOR_UNAVAILABLE = "rendered-locator-unavailable"
    DISPLAY_GUARD_MISMATCH = "display-guard-mismatch"
    CANDIDATE_UNAVAILABLE = "candidate-unavailable"
    CANDIDATE_AMBIGUOUS = "candidate-ambiguous"
    CANDIDATE_DISPLAY_GUARD_MISMATCH = "candidate-display-guard-mismatch"
    OWNER_EVIDENCE_MALFORMED = "owner-evidence-malformed"


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueueRequest(DataObjectActionRequest):
    """Bind exact Courses scope and current References evidence."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    render_result: CandidateBibliographyRenderResult
    candidates: tuple[ReferenceCandidate, ...]
    rendered_candidate_bindings: tuple[RenderedEntryCandidateBinding, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    review_projection: ReviewProjection
    state_projections: tuple[ReferenceStateProjection, ...]
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError(
                "scope must be CourseReferenceResolutionScopeEvidence"
            )
        if not isinstance(self.selections, tuple) or any(
            type(item) is not CourseReferenceSelectionEvidence
            for item in self.selections
        ):
            raise TypeError("selections must be an exact typed tuple")
        if not self.selections:
            raise CourseReferenceAuthorityError("selections must be non-empty")
        if len(self.selections) > _MAX_ITEMS:
            raise CourseReferenceAuthorityError("selection limit exceeded")
        if type(self.render_result) is not CandidateBibliographyRenderResult:
            raise TypeError(
                "render_result must be CandidateBibliographyRenderResult"
            )
        if not isinstance(self.candidates, tuple) or any(
            type(item) is not ReferenceCandidate for item in self.candidates
        ):
            raise TypeError("candidates must be an exact typed tuple")
        if not isinstance(self.rendered_candidate_bindings, tuple) or any(
            type(item) is not RenderedEntryCandidateBinding
            for item in self.rendered_candidate_bindings
        ):
            raise TypeError(
                "rendered_candidate_bindings must be an exact typed tuple"
            )
        if not isinstance(self.record_discrepancies, tuple) or any(
            type(item) is not ReferenceRecordDiscrepancy
            for item in self.record_discrepancies
        ):
            raise TypeError("record_discrepancies must be an exact typed tuple")
        if not isinstance(self.assets, tuple) or any(
            type(item) is not ReferenceAssetAuthorityEvidence
            for item in self.assets
        ):
            raise TypeError("assets must be an exact typed tuple")
        if type(self.review_projection) is not ReviewProjection:
            raise TypeError("review_projection must be a ReviewProjection")
        if not isinstance(self.state_projections, tuple) or any(
            type(item) is not ReferenceStateProjection
            for item in self.state_projections
        ):
            raise TypeError("state_projections must be an exact typed tuple")
        for label, values in (
            ("candidates", self.candidates),
            ("rendered candidate bindings", self.rendered_candidate_bindings),
            ("record discrepancies", self.record_discrepancies),
            ("assets", self.assets),
            ("state projections", self.state_projections),
        ):
            if len(values) > _MAX_ITEMS:
                raise CourseReferenceAuthorityError(f"{label} limit exceeded")
        if tuple(item.selection_id for item in self.selections) != (
            self.scope.ordered_selection_ids
        ):
            raise CourseReferenceAuthorityError(
                "selections differ from the complete Courses scope envelope"
            )
        if len(self.selections) != self.scope.total:
            raise CourseReferenceAuthorityError(
                "selection count differs from Courses scope total"
            )
        if any(
            item.scope_id != self.scope.scope_id
            or item.course_id != self.scope.course_id
            or item.manifest_id != self.scope.manifest_id
            or item.inventory_id != self.scope.inventory_id
            for item in self.selections
        ):
            raise CourseReferenceAuthorityError(
                "selections differ from the Courses scope revision"
            )
        if tuple(item.ordinal for item in self.selections) != tuple(
            range(1, len(self.selections) + 1)
        ):
            raise CourseReferenceAuthorityError(
                "selection ordinals must be contiguous"
            )
        _unique(
            (item.selection_id for item in self.selections),
            field="selection identities",
        )
        _unique(
            (item.reference_locator for item in self.selections),
            field="reference locators",
        )
        _unique(
            (item.candidate_id for item in self.candidates),
            field="candidate identities",
        )
        _unique(
            (
                item.reference_locator
                for item in self.rendered_candidate_bindings
            ),
            field="rendered candidate locators",
        )
        _unique(
            (item.binding_id for item in self.rendered_candidate_bindings),
            field="rendered candidate binding identities",
        )
        _unique(
            (item.record_id for item in self.record_discrepancies),
            field="record discrepancy identities",
        )
        _unique(
            (item.asset_observation_id for item in self.assets),
            field="asset observation identities",
        )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "course-reference-authority-queue-request",
                {
                    "asset_evidence": tuple(
                        sorted(
                            (
                                item.asset_observation_id,
                                item,
                            )
                            for item in self.assets
                        )
                    ),
                    "asset_observation_ids": tuple(
                        sorted(
                            item.asset_observation_id for item in self.assets
                        )
                    ),
                    "candidate_evidence": tuple(
                        sorted(
                            self.candidates,
                            key=lambda item: item.candidate_id,
                        )
                    ),
                    "candidate_ids": tuple(
                        sorted(item.candidate_id for item in self.candidates)
                    ),
                    "contract_id": COURSE_REFERENCE_AUTHORITY_CONTRACT_ID,
                    "observation_evidence": tuple(
                        sorted(
                            (
                                ObservedCandidateEntry(
                                    observation_id=item.observation_id,
                                    source_id=item.source_id,
                                    asserted_source_revision=(
                                        item.asserted_source_revision
                                    ),
                                    bibliography_sha256=(
                                        item.bibliography_sha256
                                    ),
                                    bibliography_byte_size=(
                                        item.bibliography_byte_size
                                    ),
                                    entry_index=item.entry_index,
                                    observed_citekey=item.observed_citekey,
                                    entry_sha256=hashlib.sha256(
                                        item.verbatim_entry.encode("utf-8")
                                    ).hexdigest(),
                                    entry_byte_size=len(
                                        item.verbatim_entry.encode("utf-8")
                                    ),
                                )
                                for source in (
                                    self.render_result.request.source.sources
                                )
                                for item in source.observations
                            ),
                            key=lambda item: item.observation_id,
                        )
                    ),
                    "record_evidence": tuple(
                        sorted(
                            self.record_discrepancies,
                            key=lambda item: item.record_id,
                        )
                    ),
                    "record_ids": tuple(
                        sorted(
                            item.record_id for item in self.record_discrepancies
                        )
                    ),
                    "render_result_id": self.render_result.result_id,
                    "rendered_entries": tuple(
                        RenderedCandidateEntryEvidence(
                            entry_id=item.entry_id,
                            citekey=item.citekey,
                            entry_type=item.entry_type,
                            normalized_fields=item.normalized_fields,
                            source_observation_ids=(
                                item.source_observation_ids
                            ),
                            rendered_sha256=hashlib.sha256(
                                item.rendered_entry
                            ).hexdigest(),
                            rendered_byte_size=len(item.rendered_entry),
                        )
                        for item in self.render_result.entries
                    ),
                    "rendered_candidate_binding_evidence": tuple(
                        sorted(
                            self.rendered_candidate_bindings,
                            key=lambda item: item.binding_id,
                        )
                    ),
                    "rendered_candidate_binding_ids": tuple(
                        sorted(
                            item.binding_id
                            for item in self.rendered_candidate_bindings
                        )
                    ),
                    "review_projection": self.review_projection,
                    "review_projection_id": (
                        self.review_projection.projection_id
                    ),
                    "scope": self.scope,
                    "scope_id": self.scope.scope_id,
                    "selections": self.selections,
                    "selection_ids": tuple(
                        item.selection_id for item in self.selections
                    ),
                    "state_projection_evidence": tuple(
                        sorted(
                            self.state_projections,
                            key=lambda item: item.projection_id,
                        )
                    ),
                    "state_projection_ids": tuple(
                        sorted(
                            item.projection_id
                            for item in self.state_projections
                        )
                    ),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueueItem(DataObjectModel):
    """One path-free candidate review item with owner-computed actions."""

    selection: CourseReferenceSelectionEvidence
    resolution: CourseReferenceItemResolution
    candidate: ReferenceCandidate | None
    observations: tuple[ObservedCandidateEntry, ...]
    rendered_entry: RenderedCandidateEntryEvidence | None
    record_matches: tuple[ReferenceRecordMatch, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    current_identity_decisions: tuple[CurrentReviewDecisionHead, ...]
    current_asset_decision: CurrentReviewDecisionHead | None
    active_authority: ActiveReferenceAuthority | None
    allowed_identity_actions: tuple[ReferenceIdentityDecision, ...]
    allowed_asset_actions: tuple[CanonicalAssetDecision, ...]
    item_revision_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.selection) is not CourseReferenceSelectionEvidence:
            raise TypeError("selection has an invalid type")
        if not isinstance(self.resolution, CourseReferenceItemResolution):
            raise TypeError("resolution has an invalid type")
        if (
            self.candidate is not None
            and type(self.candidate) is not ReferenceCandidate
        ):
            raise TypeError("candidate has an invalid type")
        if not isinstance(self.observations, tuple) or any(
            type(item) is not ObservedCandidateEntry
            for item in self.observations
        ):
            raise TypeError("observations must be an exact typed tuple")
        if (
            self.rendered_entry is not None
            and type(self.rendered_entry) is not RenderedCandidateEntryEvidence
        ):
            raise TypeError("rendered_entry has an invalid type")
        ready = self.resolution is CourseReferenceItemResolution.READY
        if ready and (
            self.candidate is None
            or self.rendered_entry is None
            or not self.observations
        ):
            raise CourseReferenceAuthorityError(
                "ready item lacks complete candidate evidence"
            )
        if not ready and (
            self.allowed_identity_actions or self.allowed_asset_actions
        ):
            raise CourseReferenceAuthorityError(
                "unresolved item cannot expose mutation actions"
            )
        if not isinstance(self.record_matches, tuple) or any(
            type(item) is not ReferenceRecordMatch
            for item in self.record_matches
        ):
            raise TypeError("record_matches must be an exact typed tuple")
        if not isinstance(self.assets, tuple) or any(
            type(item) is not ReferenceAssetAuthorityEvidence
            for item in self.assets
        ):
            raise TypeError("assets must be an exact typed tuple")
        if not isinstance(self.current_identity_decisions, tuple) or any(
            type(item) is not CurrentReviewDecisionHead
            for item in self.current_identity_decisions
        ):
            raise TypeError(
                "current_identity_decisions must be an exact typed tuple"
            )
        if (
            self.current_asset_decision is not None
            and type(self.current_asset_decision)
            is not CurrentReviewDecisionHead
        ):
            raise TypeError("current_asset_decision has an invalid type")
        if (
            self.active_authority is not None
            and type(self.active_authority) is not ActiveReferenceAuthority
        ):
            raise TypeError("active_authority has an invalid type")
        if any(
            not isinstance(item, ReferenceIdentityDecision)
            for item in self.allowed_identity_actions
        ):
            raise TypeError("allowed identity action is invalid")
        if any(
            not isinstance(item, CanonicalAssetDecision)
            for item in self.allowed_asset_actions
        ):
            raise TypeError("allowed asset action is invalid")
        object.__setattr__(
            self,
            "item_revision_id",
            _stable_id(
                "course-reference-authority-item-revision",
                {
                    "active_authority": self.active_authority,
                    "allowed_asset_actions": self.allowed_asset_actions,
                    "allowed_identity_actions": self.allowed_identity_actions,
                    "asset_evidence": self.assets,
                    "asset_observation_ids": tuple(
                        item.asset_observation_id for item in self.assets
                    ),
                    "candidate_id": (
                        None
                        if self.candidate is None
                        else self.candidate.candidate_id
                    ),
                    "current_asset_decision_id": (
                        None
                        if self.current_asset_decision is None
                        else self.current_asset_decision.decision_id
                    ),
                    "current_identity_decision_ids": tuple(
                        item.decision_id
                        for item in self.current_identity_decisions
                    ),
                    "observation_ids": tuple(
                        item.observation_id for item in self.observations
                    ),
                    "record_matches": self.record_matches,
                    "rendered_entry_id": (
                        None
                        if self.rendered_entry is None
                        else self.rendered_entry.entry_id
                    ),
                    "resolution": self.resolution,
                    "selection_id": self.selection.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueue(DataObjectActionResult):
    """Deterministic complete queue for one Courses-owned selection scope."""

    request_id: str
    scope: CourseReferenceResolutionScopeEvidence
    scope_id: str
    course_id: str
    items: tuple[CourseReferenceAuthorityQueueItem, ...]
    active_authorities: tuple[ActiveReferenceAuthority, ...]
    source_export_result_id: str
    render_result_id: str
    review_projection_id: str
    state_projection_ids: tuple[str, ...]
    control_class: str = "CONTROL"
    queue_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        for label, value in (
            ("request_id", self.request_id),
            ("scope_id", self.scope_id),
            ("source_export_result_id", self.source_export_result_id),
            ("render_result_id", self.render_result_id),
            ("review_projection_id", self.review_projection_id),
        ):
            _content_id(value, field=label)
        _bounded(self.course_id, field="course_id")
        if (
            self.scope.scope_id != self.scope_id
            or self.scope.course_id != self.course_id
            or tuple(item.selection.selection_id for item in self.items)
            != self.scope.ordered_selection_ids
        ):
            raise CourseReferenceAuthorityError(
                "queue differs from its complete Courses scope envelope"
            )
        if self.control_class != "CONTROL":
            raise CourseReferenceAuthorityError(
                "course authority queue must remain a CONTROL queue"
            )
        if not isinstance(self.items, tuple) or any(
            type(item) is not CourseReferenceAuthorityQueueItem
            for item in self.items
        ):
            raise TypeError("items must be an exact typed tuple")
        if not self.items:
            raise CourseReferenceAuthorityError("items must be non-empty")
        if not isinstance(self.active_authorities, tuple) or any(
            type(item) is not ActiveReferenceAuthority
            for item in self.active_authorities
        ):
            raise TypeError("active_authorities must be an exact typed tuple")
        _content_ids(
            self.state_projection_ids,
            field="state_projection_ids",
        )
        if tuple(item.selection.ordinal for item in self.items) != tuple(
            range(1, len(self.items) + 1)
        ):
            raise CourseReferenceAuthorityError(
                "queue items differ from Courses-owned order"
            )
        object.__setattr__(
            self,
            "queue_id",
            _stable_id(
                "course-reference-authority-queue",
                {
                    "active_authorities": self.active_authorities,
                    "control_class": self.control_class,
                    "course_id": self.course_id,
                    "item_revision_ids": tuple(
                        item.item_revision_id for item in self.items
                    ),
                    "render_result_id": self.render_result_id,
                    "request_id": self.request_id,
                    "review_projection_id": self.review_projection_id,
                    "scope": self.scope,
                    "scope_id": self.scope_id,
                    "source_export_result_id": self.source_export_result_id,
                    "state_projection_ids": self.state_projection_ids,
                },
            ),
        )


def _unresolved_item(
    selection: CourseReferenceSelectionEvidence,
    resolution: CourseReferenceItemResolution,
    *,
    rendered: RenderedCandidateEntryEvidence | None = None,
    candidate: ReferenceCandidate | None = None,
) -> CourseReferenceAuthorityQueueItem:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    selection
        Typed input governed by the function annotation.
    resolution
        Typed input governed by the function annotation.
    rendered
        Typed input governed by the function annotation.
    candidate
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    return CourseReferenceAuthorityQueueItem(
        selection=selection,
        resolution=resolution,
        candidate=candidate,
        observations=(),
        rendered_entry=rendered,
        record_matches=(),
        assets=(),
        current_identity_decisions=(),
        current_asset_decision=None,
        active_authority=None,
        allowed_identity_actions=(),
        allowed_asset_actions=(),
    )


def _validate_queue_request_freshness(
    request: CourseReferenceAuthorityQueueRequest,
) -> None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    request
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    scope = CourseReferenceResolutionScopeEvidence(
        scope_id=request.scope.scope_id,
        course_id=request.scope.course_id,
        course_title=request.scope.course_title,
        manifest_id=request.scope.manifest_id,
        manifest_sha256=request.scope.manifest_sha256,
        inventory_id=request.scope.inventory_id,
        total=request.scope.total,
        ordered_selection_ids=request.scope.ordered_selection_ids,
    )
    selections = tuple(
        CourseReferenceSelectionEvidence(
            scope_id=item.scope_id,
            selection_id=item.selection_id,
            locator_binding_id=item.locator_binding_id,
            course_id=item.course_id,
            manifest_id=item.manifest_id,
            inventory_id=item.inventory_id,
            ordinal=item.ordinal,
            origin=item.origin,
            role=item.role,
            display_citekey=item.display_citekey,
            display_citekey_status=item.display_citekey_status,
            reference_locator=item.reference_locator,
        )
        for item in request.selections
    )
    fresh = CourseReferenceAuthorityQueueRequest(
        scope=scope,
        selections=selections,
        render_result=request.render_result,
        candidates=request.candidates,
        rendered_candidate_bindings=request.rendered_candidate_bindings,
        record_discrepancies=request.record_discrepancies,
        assets=request.assets,
        review_projection=request.review_projection,
        state_projections=request.state_projections,
    )
    if fresh.request_id != request.request_id:
        raise CourseReferenceAuthorityError(
            "course authority queue request revision is stale"
        )


class CourseReferenceAuthorityProjector(
    DataObjectActionizer[
        CourseReferenceAuthorityQueueRequest,
        CourseReferenceAuthorityQueue,
    ]
):
    """Project a path-free queue without promoting candidate authority."""

    __slots__ = ()

    def action(
        self, *, request: CourseReferenceAuthorityQueueRequest
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
        if type(request) is not CourseReferenceAuthorityQueueRequest:
            raise TypeError(
                "request must be CourseReferenceAuthorityQueueRequest"
            )
        _validate_queue_request_freshness(request)
        rendered_by_id = {
            item.entry_id: item for item in request.render_result.entries
        }
        candidates_by_id = {
            item.candidate_id: item for item in request.candidates
        }
        bindings_by_locator = {
            item.reference_locator: item
            for item in request.rendered_candidate_bindings
        }
        observations = {
            item.observation_id: item
            for source in request.render_result.request.source.sources
            for item in source.observations
        }
        active_authorities = _active_authorities(
            request.state_projections,
            request.review_projection,
        )
        active_keys = {item.active_citekey for item in active_authorities}
        current_decisions = {
            item.decision_id: item
            for item in request.review_projection.human_decision_history
            if item.decision_id
            in set(request.review_projection.current_human_decision_ids)
        }
        items: list[CourseReferenceAuthorityQueueItem] = []
        for selection in request.selections:
            rendered = rendered_by_id.get(selection.reference_locator)
            if rendered is None:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.RENDERED_LOCATOR_UNAVAILABLE,
                    )
                )
                continue
            rendered_evidence = RenderedCandidateEntryEvidence(
                entry_id=rendered.entry_id,
                citekey=rendered.citekey,
                entry_type=rendered.entry_type,
                normalized_fields=rendered.normalized_fields,
                source_observation_ids=rendered.source_observation_ids,
                rendered_sha256=hashlib.sha256(
                    rendered.rendered_entry
                ).hexdigest(),
                rendered_byte_size=len(rendered.rendered_entry),
            )
            if rendered.citekey != selection.display_citekey:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.DISPLAY_GUARD_MISMATCH,
                        rendered=rendered_evidence,
                    )
                )
                continue
            binding = bindings_by_locator.get(selection.reference_locator)
            if binding is None:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.CANDIDATE_UNAVAILABLE,
                        rendered=rendered_evidence,
                    )
                )
                continue
            candidate = candidates_by_id.get(binding.candidate_id)
            if candidate is None:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.CANDIDATE_UNAVAILABLE,
                        rendered=rendered_evidence,
                    )
                )
                continue
            if (
                binding.rendered_entry_id != rendered.entry_id
                or binding.source_observation_ids
                != rendered.source_observation_ids
                or binding.source_observation_ids
                != candidate.source_observation_ids
            ):
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.OWNER_EVIDENCE_MALFORMED,
                        rendered=rendered_evidence,
                    )
                )
                continue
            if candidate.proposed_citekey != rendered.citekey:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.CANDIDATE_DISPLAY_GUARD_MISMATCH,
                        rendered=rendered_evidence,
                        candidate=candidate,
                    )
                )
                continue
            try:
                source_observations = tuple(
                    observations[item]
                    for item in rendered.source_observation_ids
                )
            except KeyError:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.OWNER_EVIDENCE_MALFORMED,
                        rendered=rendered_evidence,
                    )
                )
                continue
            observed = tuple(
                ObservedCandidateEntry(
                    observation_id=item.observation_id,
                    source_id=item.source_id,
                    asserted_source_revision=item.asserted_source_revision,
                    bibliography_sha256=item.bibliography_sha256,
                    bibliography_byte_size=item.bibliography_byte_size,
                    entry_index=item.entry_index,
                    observed_citekey=item.observed_citekey,
                    entry_sha256=hashlib.sha256(
                        item.verbatim_entry.encode("utf-8")
                    ).hexdigest(),
                    entry_byte_size=len(item.verbatim_entry.encode("utf-8")),
                )
                for item in source_observations
            )
            matches = _record_matches(
                candidate=candidate,
                rendered=rendered,
                source_observations=source_observations,
                records=request.record_discrepancies,
            )
            candidate_assets = tuple(
                sorted(
                    (
                        item
                        for item in request.assets
                        if item.candidate_id == candidate.candidate_id
                    ),
                    key=lambda item: item.asset_observation_id,
                )
            )
            identity_decisions = tuple(
                CurrentReviewDecisionHead(
                    decision_id=item.decision_id,
                    subject_id=item.subject_id,
                    context_id=item.context_id,
                    dimension=item.dimension,
                    decision=item.decision,
                    actor_id=item.actor.actor_id,
                    authority_scope=item.actor.authority_scope.value,
                    actor_verification_record_id=(
                        item.actor.verification_record_id
                    ),
                    decided_at=item.decided_at,
                )
                for item in sorted(
                    (
                        item
                        for item in current_decisions.values()
                        if item.subject_id == candidate.candidate_id
                        and item.dimension
                        is HumanReviewDimension.REFERENCE_IDENTITY
                        and item.context_id
                        in {_IDENTITY_CONTEXT, selection.course_id}
                    ),
                    key=lambda item: (item.context_id, item.decision_id),
                )
            )
            asset_decisions = tuple(
                CurrentReviewDecisionHead(
                    decision_id=item.decision_id,
                    subject_id=item.subject_id,
                    context_id=item.context_id,
                    dimension=item.dimension,
                    decision=item.decision,
                    actor_id=item.actor.actor_id,
                    authority_scope=item.actor.authority_scope.value,
                    actor_verification_record_id=(
                        item.actor.verification_record_id
                    ),
                    decided_at=item.decided_at,
                )
                for item in current_decisions.values()
                if item.subject_id == candidate.candidate_id
                and item.dimension is HumanReviewDimension.CANONICAL_ASSET
                and item.context_id == _ASSET_CONTEXT
            )
            if len(asset_decisions) > 1:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.OWNER_EVIDENCE_MALFORMED,
                        rendered=rendered_evidence,
                    )
                )
                continue
            active = next(
                (
                    item
                    for item in active_authorities
                    if item.candidate_id == candidate.candidate_id
                ),
                None,
            )
            identity_actions = [
                ReferenceIdentityDecision.REJECT,
                ReferenceIdentityDecision.DEFER,
            ]
            if active is None and candidate.proposed_citekey not in active_keys:
                identity_actions.insert(0, ReferenceIdentityDecision.ACCEPT_NEW)
            same_key_active = tuple(
                item
                for item in active_authorities
                if item.candidate_id != candidate.candidate_id
                and item.active_citekey == candidate.proposed_citekey
            )
            if active is None and same_key_active:
                identity_actions.insert(
                    0, ReferenceIdentityDecision.ACCEPT_EXISTING
                )
            if active is None and active_authorities:
                identity_actions.insert(0, ReferenceIdentityDecision.MERGE)
            asset_actions: tuple[CanonicalAssetDecision, ...] = ()
            if active is not None:
                values = [
                    CanonicalAssetDecision.REJECT,
                    CanonicalAssetDecision.DEFER,
                ]
                if any(
                    item.runtime_availability
                    is RuntimeAssetAvailability.AVAILABLE
                    for item in candidate_assets
                ):
                    values.insert(0, CanonicalAssetDecision.AUTHORIZE)
                asset_actions = tuple(values)
            items.append(
                CourseReferenceAuthorityQueueItem(
                    selection=selection,
                    resolution=CourseReferenceItemResolution.READY,
                    candidate=candidate,
                    observations=observed,
                    rendered_entry=rendered_evidence,
                    record_matches=matches,
                    assets=candidate_assets,
                    current_identity_decisions=identity_decisions,
                    current_asset_decision=(
                        asset_decisions[0] if asset_decisions else None
                    ),
                    active_authority=active,
                    allowed_identity_actions=tuple(identity_actions),
                    allowed_asset_actions=asset_actions,
                )
            )
        return CourseReferenceAuthorityQueue(
            request_id=request.request_id,
            scope=request.scope,
            scope_id=request.scope.scope_id,
            course_id=request.scope.course_id,
            items=tuple(items),
            active_authorities=active_authorities,
            source_export_result_id=request.render_result.source_export_result_id,
            render_result_id=request.render_result.result_id,
            review_projection_id=request.review_projection.projection_id,
            state_projection_ids=tuple(
                sorted(item.projection_id for item in request.state_projections)
            ),
        )


def _record_matches(
    *,
    candidate: ReferenceCandidate,
    rendered: CandidateBibliographyRenderedEntry,
    source_observations: tuple[SourceBibliographyObservation, ...],
    records: tuple[ReferenceRecordDiscrepancy, ...],
) -> tuple[ReferenceRecordMatch, ...]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    candidate
        Typed input governed by the function annotation.
    rendered
        Typed input governed by the function annotation.
    source_observations
        Typed input governed by the function annotation.
    records
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    rendered_text = rendered.rendered_entry.decode("utf-8")
    observed_text = {item.verbatim_entry for item in source_observations}
    matches = []
    for record in records:
        same_key = record.citekey == candidate.proposed_citekey
        same_observed_bytes = record.bibtex_entry in observed_text
        same_rendered_bytes = record.bibtex_entry == rendered_text
        if same_key and same_observed_bytes:
            kind = ReferenceRecordMatchKind.EXACT_OBSERVED_KEY_AND_BYTES
        elif same_key and same_rendered_bytes:
            kind = ReferenceRecordMatchKind.EXACT_RENDERED_KEY_AND_BYTES
        elif same_key:
            kind = ReferenceRecordMatchKind.SAME_KEY_DIFFERENT_BYTES
        elif same_observed_bytes:
            kind = ReferenceRecordMatchKind.SAME_OBSERVED_BYTES_DIFFERENT_KEY
        elif same_rendered_bytes:
            kind = ReferenceRecordMatchKind.SAME_RENDERED_BYTES_DIFFERENT_KEY
        else:
            continue
        encoded = record.bibtex_entry.encode("utf-8")
        matches.append(
            ReferenceRecordMatch(
                record_id=record.record_id,
                citekey=record.citekey,
                bibtex_sha256=hashlib.sha256(encoded).hexdigest(),
                bibtex_byte_size=len(encoded),
                authority_status=record.authority_status,
                kind=kind,
            )
        )
    return tuple(sorted(matches, key=lambda item: item.record_id))


def _active_authorities(
    state_projections: tuple[ReferenceStateProjection, ...],
    review_projection: ReviewProjection,
) -> tuple[ActiveReferenceAuthority, ...]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    state_projections
        Typed input governed by the function annotation.
    review_projection
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    current = {
        item.decision_id: item
        for item in review_projection.human_decision_history
        if item.decision_id in set(review_projection.current_human_decision_ids)
    }
    authorities = []
    for projection in state_projections:
        values = {
            name: _single_projection_value(projection, name)
            for name in (
                "identity_status",
                "proposed_citekey",
                "bibliographic_work_id",
                "active_citekey",
                "alias_citekeys",
                "identity_decision_id",
                "source_asset_id",
                "canonical_asset_decision_id",
                "authority_binding_id",
            )
        }
        if values["identity_status"] != "accepted":
            continue
        identity_decision_id = cast(str | None, values["identity_decision_id"])
        identity_decision = (
            None
            if identity_decision_id is None
            else current.get(identity_decision_id)
        )
        if (
            identity_decision is None
            or identity_decision.dimension
            is not HumanReviewDimension.REFERENCE_IDENTITY
            or identity_decision.decision
            not in {
                ReferenceIdentityDecision.ACCEPT_NEW.value,
                ReferenceIdentityDecision.ACCEPT_EXISTING.value,
                ReferenceIdentityDecision.MERGE.value,
            }
        ):
            continue
        projection_inputs = set(projection.authoritative_input_ids)
        if not {
            projection.subject_id,
            identity_decision.decision_id,
        }.issubset(projection_inputs):
            continue
        if (
            not isinstance(values["proposed_citekey"], str)
            or not isinstance(values["active_citekey"], str)
            or not isinstance(values["bibliographic_work_id"], str)
            or not isinstance(values["alias_citekeys"], list)
            or any(
                not isinstance(item, str)
                for item in cast(list[object], values["alias_citekeys"])
            )
        ):
            continue
        proposed_citekey = values["proposed_citekey"]
        active_citekey = values["active_citekey"]
        work_id = values["bibliographic_work_id"]
        aliases = tuple(values["alias_citekeys"])
        if (
            identity_decision.decision
            == ReferenceIdentityDecision.ACCEPT_NEW.value
        ):
            expected_work_id = _stable_id(
                "bibliographic-work",
                {
                    "candidate_id": projection.subject_id,
                    "creating_decision_id": identity_decision.decision_id,
                },
            )
            if (
                work_id != expected_work_id
                or active_citekey != proposed_citekey
                or aliases
            ):
                continue
        elif identity_decision.decision == (
            ReferenceIdentityDecision.ACCEPT_EXISTING.value
        ):
            if (
                work_id not in identity_decision.evidence_ids
                or active_citekey != proposed_citekey
            ):
                continue
        elif work_id not in identity_decision.evidence_ids or (
            proposed_citekey != active_citekey
            and proposed_citekey not in aliases
        ):
            continue
        asset_decision_id = cast(
            str | None, values["canonical_asset_decision_id"]
        )
        if asset_decision_id is None:
            if not set(identity_decision.evidence_ids).issubset(
                projection_inputs
            ):
                continue
        else:
            asset_decision = current.get(asset_decision_id)
            if (
                asset_decision is None
                or asset_decision.dimension
                is not HumanReviewDimension.CANONICAL_ASSET
                or asset_decision.decision
                != CanonicalAssetDecision.AUTHORIZE.value
                or not {
                    asset_decision.decision_id,
                    *asset_decision.evidence_ids,
                }.issubset(projection_inputs)
            ):
                continue
            work_id = values["bibliographic_work_id"]
            source_asset_id = cast(str | None, values["source_asset_id"])
            binding_id = cast(str | None, values["authority_binding_id"])
            matching_observations = tuple(
                evidence_id
                for evidence_id in asset_decision.evidence_ids
                if source_asset_id
                == _stable_id(
                    "source-asset",
                    {
                        "asset_observation_id": evidence_id,
                        "authorization_decision_id": (
                            asset_decision.decision_id
                        ),
                        "bibliographic_work_id": work_id,
                    },
                )
            )
            if len(matching_observations) != 1:
                continue
            expected_binding_id = _stable_id(
                "reference-source-asset-binding",
                {
                    "asset_observation_id": matching_observations[0],
                    "bibliographic_work_id": work_id,
                    "candidate_id": projection.subject_id,
                    "canonical_asset_decision_id": (asset_decision.decision_id),
                    "identity_decision_id": identity_decision.decision_id,
                    "source_asset_id": source_asset_id,
                },
            )
            if binding_id != expected_binding_id:
                continue
        authority = ActiveReferenceAuthority(
            candidate_id=projection.subject_id,
            state_projection_id=projection.projection_id,
            bibliographic_work_id=values["bibliographic_work_id"],
            active_citekey=values["active_citekey"],
            alias_citekeys=tuple(cast(list[str], values["alias_citekeys"])),
            identity_decision_id=cast(str, identity_decision_id),
            source_asset_id=cast(str | None, values["source_asset_id"]),
            canonical_asset_decision_id=asset_decision_id,
            authority_binding_id=cast(
                str | None, values["authority_binding_id"]
            ),
        )
        authorities.append(authority)
    by_candidate: dict[str, ActiveReferenceAuthority] = {}
    for authority in sorted(
        authorities, key=lambda item: item.state_projection_id
    ):
        previous = by_candidate.get(authority.candidate_id)
        if previous is not None:
            previous_complete = previous.source_asset_id is not None
            current_complete = authority.source_asset_id is not None
            if previous_complete == current_complete:
                raise CourseReferenceAuthorityError(
                    "candidate has ambiguous active state projections"
                )
            if previous_complete:
                continue
        by_candidate[authority.candidate_id] = authority
    return tuple(
        sorted(by_candidate.values(), key=lambda item: item.candidate_id)
    )


_MAX_ITEMS = 10_000

_MAX_TEXT = 4_096

_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")

_IDENTITY_CONTEXT = "projectkoios.references.identity"

_ASSET_CONTEXT = "projectkoios.references.canonical-asset"


def _unique(values: Iterable[str], *, field: str) -> None:
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
    items = tuple(values)
    if len(items) != len(set(items)):
        raise CourseReferenceAuthorityError(f"{field} must be unique")


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


def _single_projection_value(
    projection: ReferenceStateProjection,
    field_name: str,
) -> object | None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    projection
        Typed input governed by the function annotation.
    field_name
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    item = projection.field(field_name)
    if len(item.values) != 1 or item.values[0].value_json is None:
        return None
    value: object = json.loads(item.values[0].value_json)
    return value
