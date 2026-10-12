"""Scope-selected private bibliography projection for Courses handoff."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.candidate_bibliography import (
    CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR,
    CandidateBibliographyExportProvenance,
    CandidateBibliographyRenderedEntry,
    CandidateBibliographyRenderResult,
)
from projectkoios.references.courses.authority.errors import (
    CourseReferenceAuthorityError,
)
from projectkoios.references.courses.authority.queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceItemResolution,
)
from projectkoios.references.courses.authority.scope import (
    CourseDisplayCitekeyStatus,
)
from projectkoios.references.path_safety import (
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_ID = (
    "projectkoios.references.course-reference-selected-bibliography@0.1.0"
)
COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_VERSION = "0.1.0"
COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_STATUS = (
    "proposed-noncanonical-private-course-handoff"
)

_MAX_ITEMS = 10_000
_MAX_TEXT_BYTES = 4_096
_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectedBibliographySelection(DataObjectModel):
    """Select one predecessor item through exact Courses-owned identities."""

    new_ordinal: int
    predecessor_selection_id: str
    predecessor_locator_binding_id: str
    reference_locator: str
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus
    expected_candidate_id: str
    expected_current_authority_projection_id: str

    def __post_init__(self) -> None:
        """Validate one retained predecessor selection."""
        _positive(self.new_ordinal, field="new_ordinal")
        for label, value in (
            ("predecessor_selection_id", self.predecessor_selection_id),
            (
                "predecessor_locator_binding_id",
                self.predecessor_locator_binding_id,
            ),
            ("reference_locator", self.reference_locator),
            ("expected_candidate_id", self.expected_candidate_id),
            (
                "expected_current_authority_projection_id",
                self.expected_current_authority_projection_id,
            ),
        ):
            _content_id(value, field=label)
        validate_citekey(self.display_citekey, field="display_citekey")
        if not isinstance(
            self.display_citekey_status,
            CourseDisplayCitekeyStatus,
        ):
            raise TypeError(
                "display_citekey_status must be CourseDisplayCitekeyStatus"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectedBibliographyOmission(DataObjectModel):
    """Guard one explicit predecessor omission without deleting authority."""

    predecessor_ordinal: int
    predecessor_selection_id: str
    predecessor_locator_binding_id: str
    reference_locator: str
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus

    def __post_init__(self) -> None:
        """Validate one omitted predecessor guard."""
        _positive(self.predecessor_ordinal, field="predecessor_ordinal")
        for label, value in (
            ("predecessor_selection_id", self.predecessor_selection_id),
            (
                "predecessor_locator_binding_id",
                self.predecessor_locator_binding_id,
            ),
            ("reference_locator", self.reference_locator),
        ):
            _content_id(value, field=label)
        validate_citekey(self.display_citekey, field="display_citekey")
        if not isinstance(
            self.display_citekey_status,
            CourseDisplayCitekeyStatus,
        ):
            raise TypeError(
                "display_citekey_status must be CourseDisplayCitekeyStatus"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectedBibliographyProvenance(DataObjectModel):
    """Retain path-free provenance for one original source declaration."""

    collection_id: str
    declaration_id: str
    source_id: str
    asserted_source_revision: str | None
    bibliography_sha256: str
    bibliography_byte_size: int
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate path-free original source provenance."""
        _bounded(self.collection_id, field="collection_id")
        _content_id(self.declaration_id, field="declaration_id")
        _bounded(self.source_id, field="source_id")
        if self.asserted_source_revision is not None:
            _bounded(
                self.asserted_source_revision,
                field="asserted_source_revision",
            )
        _sha256(self.bibliography_sha256, field="bibliography_sha256")
        _nonnegative(
            self.bibliography_byte_size,
            field="bibliography_byte_size",
        )
        _content_ids(self.observation_ids, field="observation_ids")


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectedBibliographyItem(DataObjectModel):
    """Bind one retained course selection to current References authority."""

    new_ordinal: int
    predecessor_selection_id: str
    predecessor_locator_binding_id: str
    reference_locator: str
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus
    rendered_entry_id: str
    candidate_id: str
    source_observation_ids: tuple[str, ...]
    current_authority_projection_id: str
    rendered_sha256: str
    rendered_byte_size: int
    rendered_entry: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Validate one exact retained render and authority binding."""
        CourseReferenceSelectedBibliographySelection(
            new_ordinal=self.new_ordinal,
            predecessor_selection_id=self.predecessor_selection_id,
            predecessor_locator_binding_id=(
                self.predecessor_locator_binding_id
            ),
            reference_locator=self.reference_locator,
            display_citekey=self.display_citekey,
            display_citekey_status=self.display_citekey_status,
            expected_candidate_id=self.candidate_id,
            expected_current_authority_projection_id=(
                self.current_authority_projection_id
            ),
        )
        for label, value in (
            ("rendered_entry_id", self.rendered_entry_id),
            ("candidate_id", self.candidate_id),
            (
                "current_authority_projection_id",
                self.current_authority_projection_id,
            ),
        ):
            _content_id(value, field=label)
        _content_ids(
            self.source_observation_ids,
            field="source_observation_ids",
        )
        _sha256(self.rendered_sha256, field="rendered_sha256")
        _positive(self.rendered_byte_size, field="rendered_byte_size")
        if type(self.rendered_entry) is not bytes or not self.rendered_entry:
            raise TypeError("rendered_entry must be nonempty bytes")
        if len(self.rendered_entry) != self.rendered_byte_size:
            raise CourseReferenceAuthorityError(
                "rendered entry size differs from its evidence"
            )
        if hashlib.sha256(self.rendered_entry).hexdigest() != (
            self.rendered_sha256
        ):
            raise CourseReferenceAuthorityError(
                "rendered entry digest differs from its evidence"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectedBibliographyProjectionRequest(
    DataObjectActionRequest
):
    """Request an exact ordered subset of one current predecessor queue."""

    course_id: str
    revised_manifest_id: str
    revised_manifest_sha256: str
    predecessor_scope_id: str
    expected_predecessor_queue_id: str
    expected_total: int
    selections: tuple[CourseReferenceSelectedBibliographySelection, ...]
    omission: CourseReferenceSelectedBibliographyOmission
    artifact_root_alias: str
    artifact_relative_path: str
    predecessor_queue: CourseReferenceAuthorityQueue
    original_render: CandidateBibliographyRenderResult
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and identify one complete selected-render request."""
        _bounded(self.course_id, field="course_id")
        _content_id(self.revised_manifest_id, field="revised_manifest_id")
        _sha256(
            self.revised_manifest_sha256,
            field="revised_manifest_sha256",
        )
        _content_id(self.predecessor_scope_id, field="predecessor_scope_id")
        _content_id(
            self.expected_predecessor_queue_id,
            field="expected_predecessor_queue_id",
        )
        _positive(self.expected_total, field="expected_total")
        if type(self.selections) is not tuple or any(
            type(item) is not CourseReferenceSelectedBibliographySelection
            for item in self.selections
        ):
            raise TypeError("selections must be an exact typed tuple")
        if not self.selections or len(self.selections) > _MAX_ITEMS:
            raise CourseReferenceAuthorityError(
                "selected bibliography item count is out of bounds"
            )
        if len(self.selections) != self.expected_total:
            raise CourseReferenceAuthorityError(
                "selected bibliography count differs from expected_total"
            )
        if tuple(item.new_ordinal for item in self.selections) != tuple(
            range(1, len(self.selections) + 1)
        ):
            raise CourseReferenceAuthorityError(
                "selected bibliography ordinals must be contiguous"
            )
        for field_name, values in (
            (
                "selection identities",
                tuple(
                    item.predecessor_selection_id for item in self.selections
                ),
            ),
            (
                "locator binding identities",
                tuple(
                    item.predecessor_locator_binding_id
                    for item in self.selections
                ),
            ),
            (
                "reference locators",
                tuple(item.reference_locator for item in self.selections),
            ),
        ):
            _unique(values, field=field_name)
        if (
            type(self.omission)
            is not CourseReferenceSelectedBibliographyOmission
        ):
            raise TypeError("omission has an invalid type")
        validate_root_alias(self.artifact_root_alias)
        validate_relative_path(self.artifact_relative_path)
        if not self.artifact_relative_path.endswith(".bib"):
            raise CourseReferenceAuthorityError(
                "selected bibliography artifact must use a .bib path"
            )
        if type(self.predecessor_queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("predecessor_queue has an invalid type")
        if type(self.original_render) is not CandidateBibliographyRenderResult:
            raise TypeError("original_render has an invalid type")
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "course-reference-selected-bibliography-render-request",
                {
                    "artifact_relative_path": self.artifact_relative_path,
                    "artifact_root_alias": self.artifact_root_alias,
                    "contract_id": (
                        COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_ID
                    ),
                    "course_id": self.course_id,
                    "expected_total": self.expected_total,
                    "omission": self.omission,
                    "original_render_result_id": self.original_render.result_id,
                    "predecessor_scope_id": self.predecessor_scope_id,
                    "revised_manifest_id": self.revised_manifest_id,
                    "revised_manifest_sha256": self.revised_manifest_sha256,
                    "selections": self.selections,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectedBibliographyProjectionResult(
    DataObjectActionResult
):
    """Return exact private course-handoff bytes and canonical manifest."""

    request_id: str
    course_id: str
    revised_manifest_id: str
    revised_manifest_sha256: str
    predecessor_scope_id: str
    execution_predecessor_queue_id: str
    expected_total: int
    omission: CourseReferenceSelectedBibliographyOmission
    artifact_root_alias: str
    artifact_relative_path: str
    original_source_export_result_id: str
    original_render_result_id: str
    original_render_sha256: str
    original_provenance: tuple[
        CourseReferenceSelectedBibliographyProvenance, ...
    ]
    items: tuple[CourseReferenceSelectedBibliographyItem, ...]
    bibliography: bytes = field(repr=False)
    status: str = COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_STATUS
    contract_version: str = (
        COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_VERSION
    )
    bibliography_sha256: str = field(init=False)
    bibliography_byte_size: int = field(init=False)
    manifest_json: bytes = field(init=False, repr=False)
    manifest_sha256: str = field(init=False)
    manifest_byte_size: int = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and identify exact selected bytes and their manifest."""
        for label, value in (
            ("request_id", self.request_id),
            ("revised_manifest_id", self.revised_manifest_id),
            ("predecessor_scope_id", self.predecessor_scope_id),
            (
                "execution_predecessor_queue_id",
                self.execution_predecessor_queue_id,
            ),
            (
                "original_source_export_result_id",
                self.original_source_export_result_id,
            ),
            ("original_render_result_id", self.original_render_result_id),
        ):
            _content_id(value, field=label)
        _bounded(self.course_id, field="course_id")
        _sha256(
            self.revised_manifest_sha256,
            field="revised_manifest_sha256",
        )
        _sha256(self.original_render_sha256, field="original_render_sha256")
        _positive(self.expected_total, field="expected_total")
        if (
            type(self.omission)
            is not CourseReferenceSelectedBibliographyOmission
        ):
            raise TypeError("omission has an invalid type")
        validate_root_alias(self.artifact_root_alias)
        validate_relative_path(self.artifact_relative_path)
        if type(self.original_provenance) is not tuple or any(
            type(item) is not CourseReferenceSelectedBibliographyProvenance
            for item in self.original_provenance
        ):
            raise TypeError("original_provenance must be an exact typed tuple")
        if not self.original_provenance:
            raise CourseReferenceAuthorityError(
                "original provenance must not be empty"
            )
        if type(self.items) is not tuple or any(
            type(item) is not CourseReferenceSelectedBibliographyItem
            for item in self.items
        ):
            raise TypeError("items must be an exact typed tuple")
        if len(self.items) != self.expected_total:
            raise CourseReferenceAuthorityError(
                "result item count differs from expected_total"
            )
        if tuple(item.new_ordinal for item in self.items) != tuple(
            range(1, len(self.items) + 1)
        ):
            raise CourseReferenceAuthorityError(
                "result item ordinals must be contiguous"
            )
        expected_bibliography = (
            CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR.join(
                item.rendered_entry for item in self.items
            )
            + b"\n"
        )
        if self.bibliography != expected_bibliography:
            raise CourseReferenceAuthorityError(
                "selected bibliography bytes differ from ordered items"
            )
        if self.status != COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_STATUS:
            raise CourseReferenceAuthorityError(
                "selected bibliography status exceeds private handoff"
            )
        if self.contract_version != (
            COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_VERSION
        ):
            raise CourseReferenceAuthorityError(
                "selected bibliography contract version is invalid"
            )
        bibliography_sha256 = hashlib.sha256(self.bibliography).hexdigest()
        object.__setattr__(
            self,
            "bibliography_sha256",
            bibliography_sha256,
        )
        object.__setattr__(
            self,
            "bibliography_byte_size",
            len(self.bibliography),
        )
        manifest_json = _manifest_json(
            request_id=self.request_id,
            course_id=self.course_id,
            revised_manifest_id=self.revised_manifest_id,
            revised_manifest_sha256=self.revised_manifest_sha256,
            predecessor_scope_id=self.predecessor_scope_id,
            expected_total=self.expected_total,
            omission=self.omission,
            artifact_root_alias=self.artifact_root_alias,
            artifact_relative_path=self.artifact_relative_path,
            bibliography_sha256=bibliography_sha256,
            bibliography_byte_size=len(self.bibliography),
            original_source_export_result_id=(
                self.original_source_export_result_id
            ),
            original_render_result_id=self.original_render_result_id,
            original_render_sha256=self.original_render_sha256,
            original_provenance=self.original_provenance,
            items=self.items,
            status=self.status,
            contract_version=self.contract_version,
        )
        object.__setattr__(self, "manifest_json", manifest_json)
        object.__setattr__(
            self,
            "manifest_sha256",
            hashlib.sha256(manifest_json).hexdigest(),
        )
        object.__setattr__(self, "manifest_byte_size", len(manifest_json))
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "course-reference-selected-bibliography-render-result",
                {
                    "bibliography_byte_size": len(self.bibliography),
                    "bibliography_sha256": bibliography_sha256,
                    "contract_id": (
                        COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_ID
                    ),
                    "manifest_sha256": hashlib.sha256(
                        manifest_json
                    ).hexdigest(),
                    "request_id": self.request_id,
                    "status": self.status,
                },
            ),
        )


class CourseReferenceSelectedBibliographyProjectionActionizer(
    DataObjectActionizer[
        CourseReferenceSelectedBibliographyProjectionRequest,
        CourseReferenceSelectedBibliographyProjectionResult,
    ]
):
    """Project one exact locator-selected private bibliography handoff."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CourseReferenceSelectedBibliographyProjectionRequest,
    ) -> CourseReferenceSelectedBibliographyProjectionResult:
        """Return exact ordered bytes after complete owner cross-validation."""
        if type(request) is not (
            CourseReferenceSelectedBibliographyProjectionRequest
        ):
            raise TypeError("request has an invalid type")
        queue = request.predecessor_queue
        render = request.original_render
        _require_request_envelope(request)
        queue_by_selection = {
            item.selection.selection_id: item for item in queue.items
        }
        render_by_locator = {item.entry_id: item for item in render.entries}
        selected_items: list[CourseReferenceSelectedBibliographyItem] = []
        for selected in request.selections:
            queue_item = queue_by_selection.get(
                selected.predecessor_selection_id
            )
            if queue_item is None:
                raise CourseReferenceAuthorityError(
                    "selected predecessor item is unavailable"
                )
            _require_selected_queue_item(
                selected=selected,
                queue_item=queue_item,
            )
            rendered = render_by_locator.get(selected.reference_locator)
            if rendered is None:
                raise CourseReferenceAuthorityError(
                    "selected rendered locator is unavailable"
                )
            selected_items.append(
                _selected_item(
                    selected=selected,
                    queue_item=queue_item,
                    rendered=rendered,
                    queue=queue,
                )
            )
        omission_item = queue_by_selection.get(
            request.omission.predecessor_selection_id
        )
        if omission_item is None:
            raise CourseReferenceAuthorityError(
                "omitted predecessor item is unavailable"
            )
        _require_omission(
            omission=request.omission,
            queue_item=omission_item,
        )
        _require_complete_partition(request)
        items = tuple(selected_items)
        bibliography = (
            CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR.join(
                item.rendered_entry for item in items
            )
            + b"\n"
        )
        return CourseReferenceSelectedBibliographyProjectionResult(
            request_id=request.request_id,
            course_id=request.course_id,
            revised_manifest_id=request.revised_manifest_id,
            revised_manifest_sha256=request.revised_manifest_sha256,
            predecessor_scope_id=request.predecessor_scope_id,
            execution_predecessor_queue_id=queue.queue_id,
            expected_total=request.expected_total,
            omission=request.omission,
            artifact_root_alias=request.artifact_root_alias,
            artifact_relative_path=request.artifact_relative_path,
            original_source_export_result_id=render.source_export_result_id,
            original_render_result_id=render.result_id,
            original_render_sha256=render.bibliography_sha256,
            original_provenance=tuple(
                _provenance(item) for item in render.provenance
            ),
            items=items,
            bibliography=bibliography,
        )


def _require_request_envelope(
    request: CourseReferenceSelectedBibliographyProjectionRequest,
) -> None:
    queue = request.predecessor_queue
    render = request.original_render
    if queue.course_id != request.course_id:
        raise CourseReferenceAuthorityError(
            "selected bibliography course differs from predecessor queue"
        )
    if queue.scope_id != request.predecessor_scope_id:
        raise CourseReferenceAuthorityError(
            "selected bibliography predecessor scope is stale"
        )
    if queue.queue_id != request.expected_predecessor_queue_id:
        raise CourseReferenceAuthorityError(
            "selected bibliography predecessor queue is stale"
        )
    if queue.render_result_id != render.result_id or (
        queue.source_export_result_id != render.source_export_result_id
    ):
        raise CourseReferenceAuthorityError(
            "original render differs from predecessor queue evidence"
        )
    if len(queue.items) != len(request.selections) + 1:
        raise CourseReferenceAuthorityError(
            "selected bibliography must omit exactly one predecessor item"
        )
    if len(render.entries) != len(queue.items):
        raise CourseReferenceAuthorityError(
            "original render differs from predecessor queue cardinality"
        )


def _require_selected_queue_item(
    *,
    selected: CourseReferenceSelectedBibliographySelection,
    queue_item: CourseReferenceAuthorityQueueItem,
) -> None:
    selection = queue_item.selection
    if (
        selection.locator_binding_id != selected.predecessor_locator_binding_id
        or selection.reference_locator != selected.reference_locator
        or selection.display_citekey != selected.display_citekey
        or selection.display_citekey_status
        is not selected.display_citekey_status
    ):
        raise CourseReferenceAuthorityError(
            "selected predecessor locator or display guard is stale"
        )
    if queue_item.resolution is not CourseReferenceItemResolution.READY:
        raise CourseReferenceAuthorityError(
            "selected predecessor item is not ready"
        )
    if queue_item.rendered_entry is None or (
        queue_item.rendered_entry.entry_id != selected.reference_locator
    ):
        raise CourseReferenceAuthorityError(
            "selected predecessor rendered entry is stale"
        )
    if queue_item.candidate is None or queue_item.active_authority is None:
        raise CourseReferenceAuthorityError(
            "selected predecessor lacks accepted identity authority"
        )
    if queue_item.active_authority.candidate_id != (
        queue_item.candidate.candidate_id
    ):
        raise CourseReferenceAuthorityError(
            "selected predecessor authority candidate is stale"
        )
    if queue_item.candidate.candidate_id != selected.expected_candidate_id:
        raise CourseReferenceAuthorityError(
            "selected candidate differs from expected identity"
        )
    if queue_item.active_authority.state_projection_id != (
        selected.expected_current_authority_projection_id
    ):
        raise CourseReferenceAuthorityError(
            "selected authority differs from expected projection"
        )


def _selected_item(
    *,
    selected: CourseReferenceSelectedBibliographySelection,
    queue_item: CourseReferenceAuthorityQueueItem,
    rendered: CandidateBibliographyRenderedEntry,
    queue: CourseReferenceAuthorityQueue,
) -> CourseReferenceSelectedBibliographyItem:
    candidate = queue_item.candidate
    authority = queue_item.active_authority
    rendered_evidence = queue_item.rendered_entry
    if candidate is None or authority is None or rendered_evidence is None:
        raise CourseReferenceAuthorityError(
            "selected predecessor authority is incomplete"
        )
    if (
        rendered.entry_id != rendered_evidence.entry_id
        or rendered.citekey != rendered_evidence.citekey
        or rendered.source_observation_ids
        != rendered_evidence.source_observation_ids
        or hashlib.sha256(rendered.rendered_entry).hexdigest()
        != rendered_evidence.rendered_sha256
        or len(rendered.rendered_entry) != rendered_evidence.rendered_byte_size
    ):
        raise CourseReferenceAuthorityError(
            "selected rendered entry differs from queue evidence"
        )
    if candidate.source_observation_ids != rendered.source_observation_ids:
        raise CourseReferenceAuthorityError(
            "selected candidate differs from rendered observations"
        )
    if authority.state_projection_id not in queue.state_projection_ids:
        raise CourseReferenceAuthorityError(
            "selected authority projection is absent from current queue"
        )
    if authority.active_citekey != selected.display_citekey:
        raise CourseReferenceAuthorityError(
            "selected active citekey differs from Courses display guard"
        )
    return CourseReferenceSelectedBibliographyItem(
        new_ordinal=selected.new_ordinal,
        predecessor_selection_id=selected.predecessor_selection_id,
        predecessor_locator_binding_id=(
            selected.predecessor_locator_binding_id
        ),
        reference_locator=selected.reference_locator,
        display_citekey=selected.display_citekey,
        display_citekey_status=selected.display_citekey_status,
        rendered_entry_id=rendered.entry_id,
        candidate_id=candidate.candidate_id,
        source_observation_ids=rendered.source_observation_ids,
        current_authority_projection_id=authority.state_projection_id,
        rendered_sha256=hashlib.sha256(rendered.rendered_entry).hexdigest(),
        rendered_byte_size=len(rendered.rendered_entry),
        rendered_entry=rendered.rendered_entry,
    )


def _require_omission(
    *,
    omission: CourseReferenceSelectedBibliographyOmission,
    queue_item: CourseReferenceAuthorityQueueItem,
) -> None:
    selection = queue_item.selection
    if (
        selection.ordinal != omission.predecessor_ordinal
        or selection.locator_binding_id
        != omission.predecessor_locator_binding_id
        or selection.reference_locator != omission.reference_locator
        or selection.display_citekey != omission.display_citekey
        or selection.display_citekey_status
        is not omission.display_citekey_status
    ):
        raise CourseReferenceAuthorityError(
            "omission guard differs from predecessor queue"
        )


def _require_complete_partition(
    request: CourseReferenceSelectedBibliographyProjectionRequest,
) -> None:
    queue_ids = tuple(
        item.selection.selection_id for item in request.predecessor_queue.items
    )
    retained = tuple(
        item.predecessor_selection_id for item in request.selections
    )
    omitted = request.omission.predecessor_selection_id
    expected_retained = tuple(value for value in queue_ids if value != omitted)
    if retained != expected_retained:
        raise CourseReferenceAuthorityError(
            "selected predecessor order is incomplete or reordered"
        )
    if omitted in retained or set(queue_ids) != {*retained, omitted}:
        raise CourseReferenceAuthorityError(
            "selected and omitted predecessor identities do not partition scope"
        )


def _provenance(
    value: CandidateBibliographyExportProvenance,
) -> CourseReferenceSelectedBibliographyProvenance:
    return CourseReferenceSelectedBibliographyProvenance(
        collection_id=value.collection_id,
        declaration_id=value.declaration_id,
        source_id=value.source_id,
        asserted_source_revision=value.asserted_source_revision,
        bibliography_sha256=value.bibliography_sha256,
        bibliography_byte_size=value.bibliography_byte_size,
        observation_ids=value.observation_ids,
    )


def _manifest_json(
    *,
    request_id: str,
    course_id: str,
    revised_manifest_id: str,
    revised_manifest_sha256: str,
    predecessor_scope_id: str,
    expected_total: int,
    omission: CourseReferenceSelectedBibliographyOmission,
    artifact_root_alias: str,
    artifact_relative_path: str,
    bibliography_sha256: str,
    bibliography_byte_size: int,
    original_source_export_result_id: str,
    original_render_result_id: str,
    original_render_sha256: str,
    original_provenance: tuple[
        CourseReferenceSelectedBibliographyProvenance, ...
    ],
    items: tuple[CourseReferenceSelectedBibliographyItem, ...],
    status: str,
    contract_version: str,
) -> bytes:
    payload = {
        "artifact": {
            "byte_size": bibliography_byte_size,
            "relative_path": artifact_relative_path,
            "root_alias": artifact_root_alias,
            "sha256": bibliography_sha256,
        },
        "contract_id": COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_CONTRACT_ID,
        "contract_version": contract_version,
        "course_id": course_id,
        "expected_total": expected_total,
        "items": [
            {
                "candidate_id": item.candidate_id,
                "current_authority_projection_id": (
                    item.current_authority_projection_id
                ),
                "display_citekey": item.display_citekey,
                "display_citekey_status": item.display_citekey_status.value,
                "new_ordinal": item.new_ordinal,
                "predecessor_locator_binding_id": (
                    item.predecessor_locator_binding_id
                ),
                "predecessor_selection_id": item.predecessor_selection_id,
                "reference_locator": item.reference_locator,
                "rendered_byte_size": item.rendered_byte_size,
                "rendered_entry_id": item.rendered_entry_id,
                "rendered_sha256": item.rendered_sha256,
                "source_observation_ids": list(item.source_observation_ids),
            }
            for item in items
        ],
        "omission_guard": {
            "display_citekey": omission.display_citekey,
            "display_citekey_status": omission.display_citekey_status.value,
            "predecessor_locator_binding_id": (
                omission.predecessor_locator_binding_id
            ),
            "predecessor_ordinal": omission.predecessor_ordinal,
            "predecessor_selection_id": omission.predecessor_selection_id,
            "reference_locator": omission.reference_locator,
        },
        "original_provenance": [
            {
                "asserted_source_revision": item.asserted_source_revision,
                "bibliography_byte_size": item.bibliography_byte_size,
                "bibliography_sha256": item.bibliography_sha256,
                "collection_id": item.collection_id,
                "declaration_id": item.declaration_id,
                "observation_ids": list(item.observation_ids),
                "source_id": item.source_id,
            }
            for item in original_provenance
        ],
        "original_render_result_id": original_render_result_id,
        "original_render_sha256": original_render_sha256,
        "original_source_export_result_id": original_source_export_result_id,
        "predecessor_scope_id": predecessor_scope_id,
        "request_id": request_id,
        "revised_manifest_id": revised_manifest_id,
        "revised_manifest_sha256": revised_manifest_sha256,
        "status": status,
    }
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _stable_id(kind: str, value: object) -> str:
    material = json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(material).hexdigest()}"


def _json_default(value: object) -> object:
    if isinstance(
        value,
        (
            CourseReferenceSelectedBibliographySelection,
            CourseReferenceSelectedBibliographyOmission,
        ),
    ):
        return {
            name: (
                item.value
                if isinstance(item, CourseDisplayCitekeyStatus)
                else item
            )
            for name, item in (
                (field_name, getattr(value, field_name))
                for field_name in value.__dataclass_fields__
            )
        }
    raise TypeError(f"unsupported stable identity value: {type(value)!r}")


def _bounded(value: str, *, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > _MAX_TEXT_BYTES
        or any(ord(character) < 0x20 for character in value)
    ):
        raise CourseReferenceAuthorityError(
            f"{field} must be bounded non-control text"
        )
    return value


def _content_id(value: str, *, field: str) -> str:
    if type(value) is not str or _CONTENT_ID.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} must be a content ID")
    return value


def _content_ids(values: tuple[str, ...], *, field: str) -> None:
    if type(values) is not tuple or not values:
        raise CourseReferenceAuthorityError(
            f"{field} must be a nonempty exact tuple"
        )
    for value in values:
        _content_id(value, field=field)
    _unique(values, field=field)


def _sha256(value: str, *, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(
            f"{field} must be lowercase SHA-256"
        )
    return value


def _positive(value: int, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise CourseReferenceAuthorityError(f"{field} must be positive")
    return value


def _nonnegative(value: int, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise CourseReferenceAuthorityError(f"{field} must be nonnegative")
    return value


def _unique(values: tuple[str, ...], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise CourseReferenceAuthorityError(f"{field} must be unique")
