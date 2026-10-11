"""HTTP-safe immutable transport for the course reference queue."""

from __future__ import annotations

import json
from dataclasses import dataclass

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)

from ..authority.contract import COURSE_REFERENCE_AUTHORITY_CONTRACT_ID
from ..authority.queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
)
from ..authority.scope import (
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceSelectionEvidence,
)
from ..authority.service import (
    CourseReferenceAuthorityLoadActionizer,
    CourseReferenceAuthorityLoadRequest,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceQueueTransportRequest(DataObjectActionRequest):
    """Carry trusted Courses evidence into one queue transport action."""

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]

    def __post_init__(self) -> None:
        """Validate the immutable transport envelope."""
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        if not isinstance(self.selections, tuple) or any(
            type(item) is not CourseReferenceSelectionEvidence
            for item in self.selections
        ):
            raise TypeError("selections must be an exact typed tuple")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceQueueTransportResult(DataObjectActionResult):
    """Return one complete JSON queue without private owner material."""

    body_json: str

    def __post_init__(self) -> None:
        """Validate that the body is one immutable JSON object."""
        if type(self.body_json) is not str:
            raise TypeError("body_json must be str")
        value: object = json.loads(self.body_json)
        if type(value) is not dict:
            raise ValueError("queue transport body must be a JSON object")


class CourseReferenceQueueTransportActionizer(
    DataObjectActionizer[
        CourseReferenceQueueTransportRequest,
        CourseReferenceQueueTransportResult,
    ]
):
    """Load fresh owner state and serialize the complete safe queue."""

    __slots__ = ("_queue",)

    def __init__(
        self,
        *,
        queue: CourseReferenceAuthorityLoadActionizer,
    ) -> None:
        """Bind the single queue-load capability."""
        if type(queue) is not CourseReferenceAuthorityLoadActionizer:
            raise TypeError("queue has an invalid type")
        self._queue = queue

    def action(
        self,
        *,
        request: CourseReferenceQueueTransportRequest,
    ) -> CourseReferenceQueueTransportResult:
        """Return the complete safe queue as an immutable JSON body."""
        if type(request) is not CourseReferenceQueueTransportRequest:
            raise TypeError("request has an invalid type")
        queue = self._queue.action(
            request=CourseReferenceAuthorityLoadRequest(
                scope=request.scope,
                selections=request.selections,
            )
        ).queue
        return CourseReferenceQueueTransportResult(
            body_json=json.dumps(
                _queue_value(queue),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )


def _queue_value(queue: CourseReferenceAuthorityQueue) -> dict[str, object]:
    items = tuple(
        _item_value(queue, item, index=index)
        for index, item in enumerate(queue.items)
    )
    return {
        "active_authorities": tuple(
            _active_authority_value(item) for item in queue.active_authorities
        ),
        "contract_id": COURSE_REFERENCE_AUTHORITY_CONTRACT_ID,
        "control_class": "CONTROL",
        "items": items,
        "queue_id": queue.queue_id,
        "render_result_id": queue.render_result_id,
        "request_id": queue.request_id,
        "review_projection_id": queue.review_projection_id,
        "scope": {
            "course_id": queue.scope.course_id,
            "course_title": queue.scope.course_title,
            "inventory_id": queue.scope.inventory_id,
            "manifest_id": queue.scope.manifest_id,
            "manifest_sha256": queue.scope.manifest_sha256,
            "ordered_selection_ids": queue.scope.ordered_selection_ids,
            "scope_id": queue.scope.scope_id,
            "total": queue.scope.total,
        },
        "source_export_result_id": queue.source_export_result_id,
        "state_projection_ids": queue.state_projection_ids,
    }


def _item_value(
    queue: CourseReferenceAuthorityQueue,
    item: CourseReferenceAuthorityQueueItem,
    *,
    index: int,
) -> dict[str, object]:
    candidate = item.candidate
    rendered = item.rendered_entry
    selection = item.selection
    return {
        "active_authority": (
            None
            if item.active_authority is None
            else _active_authority_value(item.active_authority)
        ),
        "allowed_asset_actions": tuple(
            value.name for value in item.allowed_asset_actions
        ),
        "allowed_identity_actions": tuple(
            value.name for value in item.allowed_identity_actions
        ),
        "assets": tuple(_asset_value(value) for value in item.assets),
        "candidate": (
            None
            if candidate is None
            else {
                "authors": candidate.authors,
                "candidate_id": candidate.candidate_id,
                "citekey_status": candidate.citekey_status,
                "doi": candidate.doi,
                "eprint": candidate.eprint,
                "entry_type": candidate.entry_type,
                "identity_status": candidate.lifecycle_status,
                "isbn": candidate.isbn,
                "proposed_citekey": candidate.proposed_citekey,
                "source_observation_ids": candidate.source_observation_ids,
                "title": candidate.title,
                "url": candidate.url,
                "year": candidate.year,
            }
        ),
        "current_asset_decision": (
            None
            if item.current_asset_decision is None
            else _decision_value(item.current_asset_decision)
        ),
        "current_identity_decisions": tuple(
            _decision_value(value) for value in item.current_identity_decisions
        ),
        "item_revision_id": item.item_revision_id,
        "observations": tuple(
            {
                "asserted_source_revision": value.asserted_source_revision,
                "bibliography_byte_size": value.bibliography_byte_size,
                "bibliography_sha256": value.bibliography_sha256,
                "entry_byte_size": value.entry_byte_size,
                "entry_index": value.entry_index,
                "entry_sha256": value.entry_sha256,
                "observation_id": value.observation_id,
                "observed_citekey": value.observed_citekey,
                "source_id": value.source_id,
            }
            for value in item.observations
        ),
        "record_matches": tuple(
            {
                "authority_status": (
                    "non-authoritative-discrepancy-observation"
                ),
                "bibtex_byte_size": value.bibtex_byte_size,
                "bibtex_sha256": value.bibtex_sha256,
                "citekey": value.citekey,
                "kind": value.kind.value,
                "record_id": value.record_id,
            }
            for value in item.record_matches
        ),
        "rendered_entry": (
            None
            if rendered is None
            else {
                "citekey": rendered.citekey,
                "entry_id": rendered.entry_id,
                "entry_type": rendered.entry_type,
                "normalized_fields": rendered.normalized_fields,
                "rendered_byte_size": rendered.rendered_byte_size,
                "rendered_sha256": rendered.rendered_sha256,
                "source_observation_ids": rendered.source_observation_ids,
            }
        ),
        "resolution": item.resolution.value,
        "selection": {
            "course_id": selection.course_id,
            "display_citekey": selection.display_citekey,
            "display_citekey_status": selection.display_citekey_status.value,
            "inventory_id": selection.inventory_id,
            "locator_binding_id": selection.locator_binding_id,
            "manifest_id": selection.manifest_id,
            "next_selection_id": (
                None
                if index + 1 == len(queue.items)
                else queue.items[index + 1].selection.selection_id
            ),
            "ordinal": selection.ordinal,
            "origin": selection.origin.value,
            "previous_selection_id": (
                None
                if index == 0
                else queue.items[index - 1].selection.selection_id
            ),
            "reference_locator": selection.reference_locator,
            "role": selection.role.value,
            "scope_id": selection.scope_id,
            "selection_id": selection.selection_id,
        },
    }


def _asset_value(asset: object) -> dict[str, object]:
    from ..authority.evidence import ReferenceAssetAuthorityEvidence

    if type(asset) is not ReferenceAssetAuthorityEvidence:
        raise TypeError("asset has an invalid type")
    return {
        "asset_observation_id": asset.asset_observation_id,
        "asset_status": asset.asset_status,
        "byte_size": asset.byte_size,
        "candidate_id": asset.candidate_id,
        "document_binding_ids": asset.document_binding_ids,
        "ingestion_artifact_links": tuple(
            {
                "artifact_verification_result_id": (
                    link.artifact_verification_result_id
                ),
                "asset_observation_id": link.asset_observation_id,
                "document_id": link.document_id,
                "link_id": link.link_id,
                "source_id": link.source_id,
            }
            for link in asset.ingestion_artifact_links
        ),
        "ingestion_evidence_ids": asset.ingestion_evidence_ids,
        "rights_status": asset.rights_status,
        "runtime_availability": asset.runtime_availability.value,
        "runtime_evidence_id": asset.runtime_evidence_id,
        "sha256": asset.sha256,
    }


def _decision_value(head: object) -> dict[str, object]:
    from ..authority.authority_state import CurrentReviewDecisionHead

    if type(head) is not CurrentReviewDecisionHead:
        raise TypeError("decision head has an invalid type")
    return {
        "actor_id": head.actor_id,
        "actor_verification_record_id": head.actor_verification_record_id,
        "authority_scope": head.authority_scope,
        "context_id": head.context_id,
        "decided_at": head.decided_at,
        "decision": head.decision,
        "decision_id": head.decision_id,
        "dimension": head.dimension.value,
        "subject_id": head.subject_id,
    }


def _active_authority_value(authority: object) -> dict[str, object]:
    from ..authority.authority_state import ActiveReferenceAuthority

    if type(authority) is not ActiveReferenceAuthority:
        raise TypeError("active authority has an invalid type")
    return {
        "active_citekey": authority.active_citekey,
        "alias_citekeys": authority.alias_citekeys,
        "authority_binding_id": authority.authority_binding_id,
        "bibliographic_work_id": authority.bibliographic_work_id,
        "candidate_id": authority.candidate_id,
        "canonical_asset_decision_id": authority.canonical_asset_decision_id,
        "identity_decision_id": authority.identity_decision_id,
        "source_asset_id": authority.source_asset_id,
        "state_projection_id": authority.state_projection_id,
    }
