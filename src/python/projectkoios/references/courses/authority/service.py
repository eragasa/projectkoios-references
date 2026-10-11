"""Owner loading, idempotency replay, and post-append receipt actions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum, StrEnum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyRenderResult,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
)

from .errors import CourseReferenceAuthorityError
from .evidence import (
    ReferenceAssetAuthorityEvidence,
    ReferenceRecordDiscrepancy,
    RenderedEntryCandidateBinding,
)
from .persistence import ReferenceAuthorityDecisionResult
from .queue import (
    CourseReferenceAuthorityProjector,
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceAuthorityQueueRequest,
)
from .scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)


class CourseReferenceAuthorityFailureReason(StrEnum):
    """Stable API-mappable owner service failure categories."""

    COURSE_NOT_FOUND = "course-not-found"
    ITEM_NOT_FOUND = "item-not-found"
    EVIDENCE_STALE = "evidence-stale"
    REVISION_STALE = "revision-stale"
    TARGET_STALE = "target-stale"
    CONCURRENT_DECISION = "concurrent-decision"
    IDEMPOTENCY_CONFLICT = "idempotency-conflict"
    INVALID_DISPOSITION = "invalid-disposition"
    OWNER_MALFORMED = "owner-malformed"
    OWNER_UNAVAILABLE = "owner-unavailable"


class CourseReferenceAuthorityServiceError(RuntimeError):
    """Expose one stable reason while retaining internal exception chaining."""

    def __init__(
        self,
        reason: CourseReferenceAuthorityFailureReason,
        message: str,
    ) -> None:
        """Initialize the owner-controlled runtime capability.

        Parameters
        ----------
        reason
            Typed input governed by the function annotation.
        message
            Typed input governed by the function annotation.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityEvidenceLoadResult(DataObjectActionResult):
    """Owner-private evidence loaded behind the runtime façade."""

    render_result: CandidateBibliographyRenderResult
    candidates: tuple[ReferenceCandidate, ...]
    observations: tuple[SourceBibliographyObservation, ...]
    rendered_candidate_bindings: tuple[RenderedEntryCandidateBinding, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    evidence_revision_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.render_result) is not CandidateBibliographyRenderResult:
            raise TypeError("render_result has an invalid type")
        if not isinstance(self.candidates, tuple) or any(
            type(item) is not ReferenceCandidate for item in self.candidates
        ):
            raise TypeError("candidates must be an exact typed tuple")
        if not isinstance(self.observations, tuple) or any(
            type(item) is not SourceBibliographyObservation
            for item in self.observations
        ):
            raise TypeError("observations must be an exact typed tuple")
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
        observations_by_id = {
            item.observation_id: item for item in self.observations
        }
        candidates_by_id = {item.candidate_id: item for item in self.candidates}
        rendered_by_id = {
            item.entry_id: item for item in self.render_result.entries
        }
        if len(observations_by_id) != len(self.observations):
            raise CourseReferenceAuthorityError(
                "owner source observation identities repeat"
            )
        if len(candidates_by_id) != len(self.candidates):
            raise CourseReferenceAuthorityError(
                "owner candidate identities repeat"
            )
        render_observations = tuple(
            item
            for source in self.render_result.request.source.sources
            for item in source.observations
        )
        if any(
            observations_by_id.get(item.observation_id) != item
            for item in render_observations
        ):
            raise CourseReferenceAuthorityError(
                "owner observations differ from render observations"
            )
        if any(
            not set(item.source_observation_ids).issubset(observations_by_id)
            for item in self.candidates
        ):
            raise CourseReferenceAuthorityError(
                "owner candidate lacks its exact source observations"
            )
        for binding in self.rendered_candidate_bindings:
            rendered = rendered_by_id.get(binding.rendered_entry_id)
            candidate = candidates_by_id.get(binding.candidate_id)
            if (
                rendered is None
                or candidate is None
                or binding.source_observation_ids
                != rendered.source_observation_ids
                or binding.source_observation_ids
                != candidate.source_observation_ids
            ):
                raise CourseReferenceAuthorityError(
                    "owner rendered-candidate binding is inconsistent"
                )
        object.__setattr__(
            self,
            "evidence_revision_id",
            _stable_id(
                "course-reference-authority-owner-evidence",
                {
                    "asset_evidence": self.assets,
                    "candidate_ids": tuple(
                        item.candidate_id for item in self.candidates
                    ),
                    "observation_ids": tuple(
                        item.observation_id for item in self.observations
                    ),
                    "record_ids": tuple(
                        item.record_id for item in self.record_discrepancies
                    ),
                    "render_result_id": self.render_result.result_id,
                    "rendered_candidate_binding_ids": tuple(
                        item.binding_id
                        for item in self.rendered_candidate_bindings
                    ),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityReceiptResult(DataObjectActionResult):
    """Owner-reread post-commit receipt, never a pre-write prediction."""

    decision_result: ReferenceAuthorityDecisionResult
    preview_id: str
    refreshed_queue: CourseReferenceAuthorityQueue
    refreshed_item: CourseReferenceAuthorityQueueItem
    refreshed_queue_id: str
    refreshed_item_revision_id: str
    current_decision_id: str
    current_state_projection_id: str | None
    receipt_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.decision_result) is not ReferenceAuthorityDecisionResult:
            raise TypeError("decision_result has an invalid type")
        if type(self.refreshed_queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("refreshed_queue has an invalid type")
        if type(self.refreshed_item) is not CourseReferenceAuthorityQueueItem:
            raise TypeError("refreshed_item has an invalid type")
        _content_id(self.preview_id, field="preview_id")
        for label, value in (
            ("refreshed_queue_id", self.refreshed_queue_id),
            ("refreshed_item_revision_id", self.refreshed_item_revision_id),
            ("current_decision_id", self.current_decision_id),
        ):
            _content_id(value, field=label)
        if self.current_state_projection_id is not None:
            _content_id(
                self.current_state_projection_id,
                field="current_state_projection_id",
            )
        if (
            self.refreshed_queue_id != self.refreshed_queue.queue_id
            or self.refreshed_item_revision_id
            != self.refreshed_item.item_revision_id
            or _queue_item(
                self.refreshed_queue, self.refreshed_item.selection.selection_id
            )
            != self.refreshed_item
        ):
            raise CourseReferenceAuthorityError(
                "receipt objects differ from their owner reread identities"
            )
        if self.preview_id not in self.decision_result.decision.evidence_ids:
            raise CourseReferenceAuthorityError(
                "receipt decision lacks the exact owner preview"
            )
        if self.current_decision_id != (
            self.decision_result.decision.decision_id
        ):
            raise CourseReferenceAuthorityError(
                "receipt decision differs from the owner reread head"
            )
        object.__setattr__(
            self,
            "receipt_id",
            _stable_id(
                "reference-authority-decision-receipt",
                {
                    "current_decision_id": self.current_decision_id,
                    "preview_id": self.preview_id,
                    "current_state_projection_id": (
                        self.current_state_projection_id
                    ),
                    "decision_result_id": self.decision_result.result_id,
                    "refreshed_item_revision_id": (
                        self.refreshed_item_revision_id
                    ),
                    "refreshed_queue_id": self.refreshed_queue_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityIdempotencyLookupResult(DataObjectActionResult):
    """Represent one exact replay hit or a typed history miss."""

    found: bool
    decision_result: ReferenceAuthorityDecisionResult | None
    preview_id: str | None

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.found) is not bool:
            raise TypeError("found must be bool")
        if self.found != (self.decision_result is not None):
            raise CourseReferenceAuthorityError(
                "idempotency lookup result has inconsistent decision state"
            )
        if self.found != (self.preview_id is not None):
            raise CourseReferenceAuthorityError(
                "idempotency lookup result has inconsistent preview state"
            )
        if (
            self.decision_result is not None
            and type(self.decision_result)
            is not ReferenceAuthorityDecisionResult
        ):
            raise TypeError("decision_result has an invalid type")
        if self.preview_id is not None:
            _content_id(self.preview_id, field="preview_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityEvidenceLoadRequest(DataObjectActionRequest):
    """Request fresh private owner evidence for one exact course scope."""

    scope: CourseReferenceResolutionScopeEvidence
    catalog_candidates: tuple[ReferenceCandidate, ...]
    catalog_observations: tuple[SourceBibliographyObservation, ...]
    catalog_assets: tuple[SourceAssetRecord, ...]

    def __post_init__(self) -> None:
        """Validate exact immutable evidence-load inputs."""
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        for values, expected, label in (
            (self.catalog_candidates, ReferenceCandidate, "catalog_candidates"),
            (
                self.catalog_observations,
                SourceBibliographyObservation,
                "catalog_observations",
            ),
            (self.catalog_assets, SourceAssetRecord, "catalog_assets"),
        ):
            if not isinstance(values, tuple) or any(
                type(item) is not expected for item in values
            ):
                raise TypeError(f"{label} must be an exact typed tuple")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityLoadRequest(DataObjectActionRequest):
    """Request one fresh queue plus its exact owner evidence."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]

    def __post_init__(self) -> None:
        """Validate the complete Courses-owned load envelope."""
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        if not isinstance(self.selections, tuple) or any(
            type(item) is not CourseReferenceSelectionEvidence
            for item in self.selections
        ):
            raise TypeError("selections must be an exact typed tuple")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityLoadResult(DataObjectActionResult):
    """Return a fresh queue and the exact evidence used to project it."""

    queue: CourseReferenceAuthorityQueue
    evidence: CourseReferenceAuthorityEvidenceLoadResult

    def __post_init__(self) -> None:
        """Validate the load result graph without performing owner I/O."""
        if type(self.queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("queue has an invalid type")
        if (
            type(self.evidence)
            is not CourseReferenceAuthorityEvidenceLoadResult
        ):
            raise TypeError("evidence has an invalid type")


class CourseReferenceAuthorityLoadActionizer(
    DataObjectActionizer[
        CourseReferenceAuthorityLoadRequest,
        CourseReferenceAuthorityLoadResult,
    ]
):
    """Load schema-5 and filesystem evidence and project one fresh queue."""

    __slots__ = ("_catalog", "_evidence_loader")

    def __init__(
        self,
        *,
        catalog: ReferenceCatalog,
        evidence_loader: DataObjectActionizer[
            CourseReferenceAuthorityEvidenceLoadRequest,
            CourseReferenceAuthorityEvidenceLoadResult,
        ],
    ) -> None:
        """Bind the catalog and exact evidence-loading capability."""
        if type(catalog) is not ReferenceCatalog:
            raise TypeError("catalog must be a ReferenceCatalog")
        if not isinstance(evidence_loader, DataObjectActionizer):
            raise TypeError("evidence_loader must be a DataObjectActionizer")
        self._catalog = catalog
        self._evidence_loader = evidence_loader

    def action(
        self,
        *,
        request: CourseReferenceAuthorityLoadRequest,
    ) -> CourseReferenceAuthorityLoadResult:
        """Return one fresh owner queue and its exact evidence."""
        if type(request) is not CourseReferenceAuthorityLoadRequest:
            raise TypeError("request has an invalid type")
        try:
            evidence = self._evidence_loader.action(
                request=CourseReferenceAuthorityEvidenceLoadRequest(
                    scope=request.scope,
                    catalog_candidates=self._catalog.read_candidates(),
                    catalog_observations=self._catalog.read_observations(),
                    catalog_assets=self._catalog.read_source_assets(),
                )
            )
            queue_request = CourseReferenceAuthorityQueueRequest(
                scope=request.scope,
                selections=request.selections,
                render_result=evidence.render_result,
                candidates=evidence.candidates,
                rendered_candidate_bindings=evidence.rendered_candidate_bindings,
                record_discrepancies=evidence.record_discrepancies,
                assets=evidence.assets,
                review_projection=self._catalog.read_review_projection(),
                state_projections=self._catalog.read_state_projections(),
            )
            queue = CourseReferenceAuthorityProjector().action(
                request=queue_request
            )
        except CourseReferenceAuthorityServiceError:
            raise
        except (OSError, RuntimeError) as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.OWNER_UNAVAILABLE,
                "References authority evidence is unavailable",
            ) from error
        except Exception as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.OWNER_MALFORMED,
                "References authority evidence is malformed",
            ) from error
        return CourseReferenceAuthorityLoadResult(
            queue=queue,
            evidence=evidence,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityIdempotencyLookupRequest(DataObjectActionRequest):
    """Request exact append-only idempotency history reconstruction."""

    idempotency_scope_id: str
    idempotency_request_id: str
    dimension: HumanReviewDimension
    subject_id: str

    def __post_init__(self) -> None:
        """Validate structural lookup inputs without reading owner state."""
        if not all(
            type(value) is str and value
            for value in (
                self.idempotency_scope_id,
                self.idempotency_request_id,
                self.subject_id,
            )
        ):
            raise ValueError("idempotency lookup identities must be nonempty")
        if not isinstance(self.dimension, HumanReviewDimension):
            raise TypeError("dimension has an invalid type")


class ReferenceAuthorityIdempotencyLookupActionizer(
    DataObjectActionizer[
        ReferenceAuthorityIdempotencyLookupRequest,
        ReferenceAuthorityIdempotencyLookupResult,
    ]
):
    """Reconstruct one exact idempotent append result from schema-5 history."""

    __slots__ = ("_catalog",)

    def __init__(self, *, catalog: ReferenceCatalog) -> None:
        """Bind the schema-5 catalog capability."""
        if type(catalog) is not ReferenceCatalog:
            raise TypeError("catalog must be a ReferenceCatalog")
        self._catalog = catalog

    def action(
        self,
        *,
        request: ReferenceAuthorityIdempotencyLookupRequest,
    ) -> ReferenceAuthorityIdempotencyLookupResult:
        """Return the exact matching history result or a typed miss."""
        if type(request) is not ReferenceAuthorityIdempotencyLookupRequest:
            raise TypeError("request has an invalid type")
        review = self._catalog.read_review_projection()
        matches = tuple(
            item
            for item in review.human_decision_history
            if request.idempotency_scope_id in item.evidence_ids
        )
        if not matches:
            return ReferenceAuthorityIdempotencyLookupResult(
                found=False,
                decision_result=None,
                preview_id=None,
            )
        if len(matches) != 1:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.OWNER_MALFORMED,
                "idempotency scope has multiple owner decisions",
            )
        decision = matches[0]
        if (
            request.idempotency_request_id not in decision.evidence_ids
            or decision.dimension is not request.dimension
            or decision.subject_id != request.subject_id
        ):
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.IDEMPOTENCY_CONFLICT,
                "idempotency key was reused with different decision inputs",
            )
        preview_prefix = (
            "reference-identity-decision-preview:sha256:"
            if request.dimension is HumanReviewDimension.REFERENCE_IDENTITY
            else "canonical-asset-decision-preview:sha256:"
        )
        request_prefix = (
            "append-reference-identity-decision-request:sha256:"
            if request.dimension is HumanReviewDimension.REFERENCE_IDENTITY
            else "append-canonical-asset-decision-request:sha256:"
        )
        preview_ids = tuple(
            item
            for item in decision.evidence_ids
            if item.startswith(preview_prefix)
        )
        request_ids = tuple(
            item
            for item in decision.evidence_ids
            if item.startswith(request_prefix)
        )
        if len(preview_ids) != 1 or len(request_ids) != 1:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.OWNER_MALFORMED,
                "idempotent decision lacks exact owner receipt identities",
            )
        accepting_identity = (
            decision.dimension is HumanReviewDimension.REFERENCE_IDENTITY
            and decision.decision
            in {
                ReferenceIdentityDecision.ACCEPT_EXISTING.value,
                ReferenceIdentityDecision.ACCEPT_NEW.value,
                ReferenceIdentityDecision.MERGE.value,
            }
        )
        authorizing_asset = (
            decision.dimension is HumanReviewDimension.CANONICAL_ASSET
            and decision.decision == CanonicalAssetDecision.AUTHORIZE.value
        )
        projection: ReferenceStateProjection | None = None
        if accepting_identity or authorizing_asset:
            field_name = (
                "identity_decision_id"
                if accepting_identity
                else "canonical_asset_decision_id"
            )
            projections = tuple(
                item
                for item in self._catalog.read_state_projections()
                if item.subject_id == decision.subject_id
                and _single_projection_value(item, field_name)
                == decision.decision_id
                and (
                    not accepting_identity
                    or _single_projection_value(
                        item,
                        "canonical_asset_decision_id",
                    )
                    is None
                )
            )
            if len(projections) != 1:
                raise CourseReferenceAuthorityServiceError(
                    CourseReferenceAuthorityFailureReason.OWNER_MALFORMED,
                    "idempotent decision lacks one exact state projection",
                )
            projection = projections[0]
        return ReferenceAuthorityIdempotencyLookupResult(
            found=True,
            decision_result=ReferenceAuthorityDecisionResult(
                request_id=request_ids[0],
                decision=decision,
                state_projection=projection,
            ),
            preview_id=preview_ids[0],
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityReceiptRequest(DataObjectActionRequest):
    """Request a post-append owner reread receipt."""

    decision_result: ReferenceAuthorityDecisionResult
    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    selection_id: str
    preview_id: str

    def __post_init__(self) -> None:
        """Validate complete receipt reconstruction inputs."""
        if type(self.decision_result) is not ReferenceAuthorityDecisionResult:
            raise TypeError("decision_result has an invalid type")
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        if not isinstance(self.selections, tuple) or any(
            type(item) is not CourseReferenceSelectionEvidence
            for item in self.selections
        ):
            raise TypeError("selections must be an exact typed tuple")
        if type(self.selection_id) is not str or not self.selection_id:
            raise ValueError("selection_id must be nonempty")
        if type(self.preview_id) is not str or not self.preview_id:
            raise ValueError("preview_id must be nonempty")


class ReferenceAuthorityReceiptActionizer(
    DataObjectActionizer[
        ReferenceAuthorityReceiptRequest,
        ReferenceAuthorityReceiptResult,
    ]
):
    """Reread owner state and verify one exact post-append receipt."""

    __slots__ = ("_loader",)

    def __init__(
        self, *, loader: CourseReferenceAuthorityLoadActionizer
    ) -> None:
        """Bind the fresh queue-loading action capability."""
        if type(loader) is not CourseReferenceAuthorityLoadActionizer:
            raise TypeError("loader has an invalid type")
        self._loader = loader

    def action(
        self,
        *,
        request: ReferenceAuthorityReceiptRequest,
    ) -> ReferenceAuthorityReceiptResult:
        """Return a receipt only after the exact owner reread succeeds."""
        if type(request) is not ReferenceAuthorityReceiptRequest:
            raise TypeError("request has an invalid type")
        loaded = self._loader.action(
            request=CourseReferenceAuthorityLoadRequest(
                scope=request.scope,
                selections=request.selections,
            )
        )
        queue = loaded.queue
        try:
            item = _queue_item(queue, request.selection_id)
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.ITEM_NOT_FOUND,
                "course reference item is unavailable after append",
            ) from error
        result = request.decision_result
        heads = (
            item.current_identity_decisions
            if result.decision.dimension
            is HumanReviewDimension.REFERENCE_IDENTITY
            else (
                ()
                if item.current_asset_decision is None
                else (item.current_asset_decision,)
            )
        )
        if result.decision.decision_id not in {
            head.decision_id for head in heads
        }:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION,
                "appended decision is not the owner-reread current head",
            )
        state_projection_id = (
            None
            if result.state_projection is None
            else result.state_projection.projection_id
        )
        if state_projection_id is not None and state_projection_id not in (
            queue.state_projection_ids
        ):
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
                "appended projection is absent from owner reread",
            )
        return ReferenceAuthorityReceiptResult(
            decision_result=result,
            preview_id=request.preview_id,
            refreshed_queue=queue,
            refreshed_item=item,
            refreshed_queue_id=queue.queue_id,
            refreshed_item_revision_id=item.item_revision_id,
            current_decision_id=result.decision.decision_id,
            current_state_projection_id=state_projection_id,
        )


def _service_operation_error(
    error: Exception,
    *,
    operation: str,
) -> CourseReferenceAuthorityServiceError:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    error
        Typed input governed by the function annotation.
    operation
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    import sqlite3

    from projectkoios.references.catalog import (
        CatalogConflictError,
        CatalogSchemaError,
    )

    if isinstance(error, CatalogConflictError):
        reason = CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION
        detail = f"{operation} encountered concurrent authority state"
    elif isinstance(error, (OSError, sqlite3.Error, RuntimeError)):
        reason = CourseReferenceAuthorityFailureReason.OWNER_UNAVAILABLE
        detail = f"{operation} owner is unavailable"
    elif isinstance(
        error,
        (
            CatalogSchemaError,
            CourseReferenceAuthorityError,
            TypeError,
            ValueError,
            AttributeError,
        ),
    ):
        reason = CourseReferenceAuthorityFailureReason.OWNER_MALFORMED
        detail = f"{operation} owner evidence is malformed"
    else:
        reason = CourseReferenceAuthorityFailureReason.OWNER_MALFORMED
        detail = f"{operation} failed owner validation"
    return CourseReferenceAuthorityServiceError(reason, detail)


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
