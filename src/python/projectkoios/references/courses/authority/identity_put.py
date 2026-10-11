"""Typed idempotent identity decision PUT owner operation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.identity import (
    ReferenceCandidate,
)
from projectkoios.references.review import (
    HumanReviewDimension,
    ReferenceIdentityDecision,
    ReviewActorProvenance,
)

from .authority_state import (
    ActiveReferenceAuthority,
    CurrentReviewDecisionHead,
)
from .errors import CourseReferenceAuthorityError
from .identity_preview import (
    ReferenceIdentityDecisionPreviewRequest,
    ReferenceIdentityDecisionPreviewResult,
)
from .persistence import (
    AppendReferenceIdentityDecisionRequest,
    ReferenceIdentityDecisionAppendActionizer,
)
from .plans import ReferenceIdentityDecisionPreview
from .put_result import (
    ReferenceAuthorityDecisionPutResult,
)
from .queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceItemResolution,
)
from .service import (
    CourseReferenceAuthorityFailureReason,
    CourseReferenceAuthorityLoadActionizer,
    CourseReferenceAuthorityLoadRequest,
    CourseReferenceAuthorityServiceError,
    ReferenceAuthorityIdempotencyLookupActionizer,
    ReferenceAuthorityIdempotencyLookupRequest,
    ReferenceAuthorityReceiptActionizer,
    ReferenceAuthorityReceiptRequest,
    ReferenceAuthorityReceiptResult,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PutReferenceIdentityDecisionRequest(DataObjectActionRequest):
    """Bind one identity preview to stateless append and retry inputs."""

    preview_request: ReferenceIdentityDecisionPreviewRequest
    expected_preview_id: str
    expected_preview_result_id: str
    expected_queue_id: str
    expected_item_revision_id: str
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    idempotency_key: str
    idempotency_scope_id: str = field(init=False)
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.preview_request) is not (
            ReferenceIdentityDecisionPreviewRequest
        ):
            raise TypeError("preview_request has an invalid type")
        for label, value in (
            ("expected_preview_id", self.expected_preview_id),
            ("expected_preview_result_id", self.expected_preview_result_id),
            ("expected_queue_id", self.expected_queue_id),
            ("expected_item_revision_id", self.expected_item_revision_id),
        ):
            _content_id(value, field=label)
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor has an invalid type")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        if type(self.idempotency_key) is not str or not self.idempotency_key:
            raise ValueError("idempotency_key must be nonempty")
        try:
            encoded_key = self.idempotency_key.encode(
                "utf-8",
                errors="strict",
            )
        except UnicodeEncodeError as error:
            raise ValueError("idempotency_key must be valid UTF-8") from error
        if len(encoded_key) > 1_024:
            raise ValueError("idempotency_key exceeds its byte limit")
        scope_id = _stable_id(
            "reference-authority-idempotency-scope",
            {
                "actor": self.actor,
                "actor_verification_record_id": (
                    self.actor.verification_record_id
                ),
                "course_id": self.preview_request.scope.course_id,
                "idempotency_key": self.idempotency_key,
                "operation": "reference-identity",
                "scope_id": self.preview_request.scope.scope_id,
                "selection_id": self.preview_request.selection_id,
            },
        )
        object.__setattr__(self, "idempotency_scope_id", scope_id)
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "reference-authority-idempotency-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "expected_item_revision_id": (
                        self.expected_item_revision_id
                    ),
                    "expected_preview_id": self.expected_preview_id,
                    "expected_preview_result_id": (
                        self.expected_preview_result_id
                    ),
                    "expected_queue_id": self.expected_queue_id,
                    "idempotency_scope_id": scope_id,
                    "preview_request_id": self.preview_request.request_id,
                    "rationale": self.rationale,
                },
            ),
        )


class PutReferenceIdentityDecisionActionizer(
    DataObjectActionizer[
        PutReferenceIdentityDecisionRequest,
        ReferenceAuthorityDecisionPutResult,
    ]
):
    """Append or replay one identity PUT and return its safe reread result."""

    __slots__ = ("_catalog", "_loader", "_lookup", "_receipt")

    def __init__(
        self,
        *,
        catalog: ReferenceCatalog,
        loader: CourseReferenceAuthorityLoadActionizer,
        lookup: ReferenceAuthorityIdempotencyLookupActionizer,
        receipt: ReferenceAuthorityReceiptActionizer,
    ) -> None:
        """Bind the exact catalog, load, lookup, and receipt capabilities."""
        if type(catalog) is not ReferenceCatalog:
            raise TypeError("catalog has an invalid type")
        if type(loader) is not CourseReferenceAuthorityLoadActionizer:
            raise TypeError("loader has an invalid type")
        if type(lookup) is not ReferenceAuthorityIdempotencyLookupActionizer:
            raise TypeError("lookup has an invalid type")
        if type(receipt) is not ReferenceAuthorityReceiptActionizer:
            raise TypeError("receipt has an invalid type")
        self._catalog = catalog
        self._loader = loader
        self._lookup = lookup
        self._receipt = receipt

    def action(
        self,
        *,
        request: PutReferenceIdentityDecisionRequest,
    ) -> ReferenceAuthorityDecisionPutResult:
        """Append or replay one stateless identity decision."""
        if type(request) is not PutReferenceIdentityDecisionRequest:
            raise TypeError("request has an invalid type")
        try:
            receipt = _put_identity_decision(
                request=request,
                catalog=self._catalog,
                loader=self._loader,
                lookup=self._lookup,
                receipt_actionizer=self._receipt,
            )
        except CourseReferenceAuthorityServiceError:
            raise
        except Exception as error:
            raise _service_operation_error(
                error,
                operation="identity decision PUT",
            ) from error
        decision_result = receipt.decision_result
        return ReferenceAuthorityDecisionPutResult(
            put_request_id=request.request_id,
            decision_append_request_id=decision_result.request_id,
            decision_id=decision_result.decision.decision_id,
            state_projection_id=(
                None
                if decision_result.state_projection is None
                else decision_result.state_projection.projection_id
            ),
            preview_id=receipt.preview_id,
            receipt_id=receipt.receipt_id,
            refreshed_queue_id=receipt.refreshed_queue_id,
            refreshed_item_revision_id=receipt.refreshed_item_revision_id,
            current_decision_id=receipt.current_decision_id,
            current_state_projection_id=receipt.current_state_projection_id,
        )


def _put_identity_decision(
    *,
    request: PutReferenceIdentityDecisionRequest,
    catalog: ReferenceCatalog,
    loader: CourseReferenceAuthorityLoadActionizer,
    lookup: ReferenceAuthorityIdempotencyLookupActionizer,
    receipt_actionizer: ReferenceAuthorityReceiptActionizer,
) -> ReferenceAuthorityReceiptResult:
    """Implement one identity PUT behind its sole public action boundary."""
    preview_request = request.preview_request
    loaded = loader.action(
        request=CourseReferenceAuthorityLoadRequest(
            scope=preview_request.scope,
            selections=preview_request.selections,
        )
    )
    queue = loaded.queue
    try:
        item = _queue_item(queue, preview_request.selection_id)
        candidate = _ready_candidate(item)
    except CourseReferenceAuthorityError as error:
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
            "course reference item evidence is unavailable",
        ) from error
    lookup_request = ReferenceAuthorityIdempotencyLookupRequest(
        idempotency_scope_id=request.idempotency_scope_id,
        idempotency_request_id=request.request_id,
        dimension=HumanReviewDimension.REFERENCE_IDENTITY,
        subject_id=candidate.candidate_id,
    )
    existing = lookup.action(request=lookup_request)
    if existing.found:
        assert existing.decision_result is not None
        assert existing.preview_id is not None
        return receipt_actionizer.action(
            request=ReferenceAuthorityReceiptRequest(
                decision_result=existing.decision_result,
                scope=preview_request.scope,
                selections=preview_request.selections,
                selection_id=preview_request.selection_id,
                preview_id=existing.preview_id,
            )
        )
    if (
        queue.queue_id != request.expected_queue_id
        or item.item_revision_id != request.expected_item_revision_id
    ):
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.REVISION_STALE,
            "identity PUT queue or item revision is stale",
        )
    preview = _identity_preview(queue=queue, request=preview_request)
    if preview.preview_id != request.expected_preview_id:
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
            "identity PUT preview evidence is stale",
        )
    preview_result = _identity_preview_result(
        request=preview_request,
        preview=preview,
    )
    if preview_result.result_id != request.expected_preview_result_id:
        raise CourseReferenceAuthorityServiceError(
            CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
            "identity PUT preview result is stale",
        )
    try:
        fresh = loader.action(
            request=CourseReferenceAuthorityLoadRequest(
                scope=preview_request.scope,
                selections=preview_request.selections,
            )
        )
        fresh_preview = _identity_preview(
            queue=fresh.queue,
            request=preview_request,
        )
        if fresh_preview.preview_id != preview.preview_id:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
                "identity preview evidence is stale",
            )
        result = ReferenceIdentityDecisionAppendActionizer(
            catalog=catalog,
            candidates=fresh.evidence.candidates,
            observations=fresh.evidence.observations,
        ).action(
            request=AppendReferenceIdentityDecisionRequest(
                preview=fresh_preview,
                actor=request.actor,
                rationale=request.rationale,
                decided_at=request.decided_at,
                idempotency_evidence_ids=tuple(
                    sorted({request.idempotency_scope_id, request.request_id})
                ),
            )
        )
    except CourseReferenceAuthorityServiceError:
        raise
    except Exception as error:
        failure = _service_operation_error(
            error,
            operation="identity decision PUT",
        )
        if (
            failure.reason
            is not CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION
        ):
            raise failure from error
        raced = lookup.action(request=lookup_request)
        if not raced.found:
            raise failure from error
        assert raced.decision_result is not None
        assert raced.preview_id is not None
        return receipt_actionizer.action(
            request=ReferenceAuthorityReceiptRequest(
                decision_result=raced.decision_result,
                scope=preview_request.scope,
                selections=preview_request.selections,
                selection_id=preview_request.selection_id,
                preview_id=raced.preview_id,
            )
        )
    return receipt_actionizer.action(
        request=ReferenceAuthorityReceiptRequest(
            decision_result=result,
            scope=preview_request.scope,
            selections=preview_request.selections,
            selection_id=preview_request.selection_id,
            preview_id=preview.preview_id,
        )
    )


def _identity_preview(
    *,
    queue: CourseReferenceAuthorityQueue,
    request: ReferenceIdentityDecisionPreviewRequest,
) -> ReferenceIdentityDecisionPreview:
    """Reconstruct one immutable identity preview from an exact fresh queue."""
    try:
        item = _queue_item(queue, request.selection_id)
        if request.target_state_projection_id is not None:
            _target_authority(queue, request.target_state_projection_id)
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
        _require_expected_head(current, request.expected_current_decision_id)
        return ReferenceIdentityDecisionPreview(
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


def _identity_preview_result(
    *,
    request: ReferenceIdentityDecisionPreviewRequest,
    preview: ReferenceIdentityDecisionPreview,
) -> ReferenceIdentityDecisionPreviewResult:
    """Project the exact safe result identity used by the external PUT."""
    item = _queue_item(preview.queue, preview.selection_id)
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
