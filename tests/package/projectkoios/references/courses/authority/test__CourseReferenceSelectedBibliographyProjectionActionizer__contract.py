"""Contract tests for scope-selected private bibliography projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyExportRequest,
    CandidateBibliographyRenderer,
    CandidateBibliographyRenderRequest,
    CandidateBibliographyRenderResult,
    CandidateBibliographySourceDeclaration,
)
from projectkoios.references.courses.authority.authority_state import (
    ActiveReferenceAuthority,
)
from projectkoios.references.courses.authority.errors import (
    CourseReferenceAuthorityError,
)
from projectkoios.references.courses.authority.evidence import (
    ObservedCandidateEntry,
    RenderedCandidateEntryEvidence,
)
from projectkoios.references.courses.authority.queue import (
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueItem,
    CourseReferenceItemResolution,
)
from projectkoios.references.courses.authority.scope import (
    CourseDisplayCitekeyStatus,
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceRole,
    CourseReferenceSelectionEvidence,
    CourseReferenceSelectionOrigin,
)
from projectkoios.references.courses.authority.selected_bibliography import (
    COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_STATUS,
    CourseReferenceSelectedBibliographyOmission,
    CourseReferenceSelectedBibliographyProjectionActionizer,
    CourseReferenceSelectedBibliographyProjectionRequest,
    CourseReferenceSelectedBibliographySelection,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)
from projectkoios.references.path_safety import RootStorageClass


def _cid(kind: str, value: str) -> str:
    return f"{kind}:sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _locator_binding_id(
    *,
    ordinal: int,
    citekey: str,
    locator: str,
) -> str:
    material = json.dumps(
        {
            "contract_version": "1.0",
            "display_citekey": citekey,
            "display_citekey_status": "observed",
            "ordinal": ordinal,
            "reference_locator": locator,
            "reference_owner": "projectkoios-references",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return (
        "course-reference-locator-binding:sha256:"
        + hashlib.sha256(material).hexdigest()
    )


def _render(tmp_path: Path) -> CandidateBibliographyRenderResult:
    path = tmp_path / "original.bib"
    path.write_text(
        "\n\n".join(
            (
                (
                    "@book{first2024, author={First, Alice}, "
                    "title={First Work}, year={2024}}"
                ),
                (
                    "@book{omit2025, author={Omit, Bea}, "
                    "title={Omitted Work}, year={2025}}"
                ),
                (
                    "@article{third2026, author={Third, Cal}, "
                    "title={Third Work}, journal={Examples}, year={2026}}"
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    content = path.read_bytes()
    imported = load_bibliography(
        path,
        source_id="sanitized:selected-render",
        source_revision=f"sha256:{hashlib.sha256(content).hexdigest()}",
        source_path="fixtures/original.bib",
        storage_class=RootStorageClass.LOCAL,
    )
    return CandidateBibliographyRenderer().action(
        request=CandidateBibliographyRenderRequest(
            source=CandidateBibliographyExportRequest(
                sources=(
                    CandidateBibliographySourceDeclaration(
                        collection_id="selected-render",
                        observations=imported.observations,
                    ),
                )
            )
        )
    )


def _queue(
    render: CandidateBibliographyRenderResult,
) -> CourseReferenceAuthorityQueue:
    observations = tuple(
        observation
        for declaration in render.request.source.sources
        for observation in declaration.observations
    )
    by_observation = {item.observation_id: item for item in observations}
    scope_id = _cid("course-reference-resolution-scope", "predecessor")
    manifest_id = _cid("course-authoring-manifest", "predecessor")
    inventory_id = _cid("course-source-inventory", "predecessor")
    selection_ids = tuple(
        _cid("course-reference-selection", f"selection-{index}")
        for index in range(1, 4)
    )
    scope = CourseReferenceResolutionScopeEvidence(
        scope_id=scope_id,
        course_id="synthetic-course",
        course_title="Synthetic Course",
        manifest_id=manifest_id,
        manifest_sha256=hashlib.sha256(b"predecessor").hexdigest(),
        inventory_id=inventory_id,
        total=3,
        ordered_selection_ids=selection_ids,
    )
    items: list[CourseReferenceAuthorityQueueItem] = []
    authorities: list[ActiveReferenceAuthority] = []
    projection_ids: list[str] = []
    for ordinal, (selection_id, rendered) in enumerate(
        zip(selection_ids, render.entries, strict=True),
        start=1,
    ):
        source = by_observation[rendered.source_observation_ids[0]]
        imported_candidate = next(
            candidate
            for candidate in _candidates(render)
            if candidate.proposed_citekey == rendered.citekey
        )
        selection = CourseReferenceSelectionEvidence(
            scope_id=scope_id,
            selection_id=selection_id,
            locator_binding_id=_locator_binding_id(
                ordinal=ordinal,
                citekey=rendered.citekey,
                locator=rendered.entry_id,
            ),
            course_id=scope.course_id,
            manifest_id=manifest_id,
            inventory_id=inventory_id,
            ordinal=ordinal,
            origin=CourseReferenceSelectionOrigin.PRESERVED_MANUSCRIPT,
            role=CourseReferenceRole.MANUSCRIPT_BIBLIOGRAPHY,
            display_citekey=rendered.citekey,
            display_citekey_status=CourseDisplayCitekeyStatus.OBSERVED,
            reference_locator=rendered.entry_id,
        )
        projection_id = _cid("reference-state-projection", f"state-{ordinal}")
        authority = ActiveReferenceAuthority(
            candidate_id=imported_candidate.candidate_id,
            state_projection_id=projection_id,
            bibliographic_work_id=_cid(
                "reference-bibliographic-work",
                f"work-{ordinal}",
            ),
            active_citekey=rendered.citekey,
            alias_citekeys=(),
            identity_decision_id=_cid(
                "human-review-decision",
                f"decision-{ordinal}",
            ),
            source_asset_id=None,
            canonical_asset_decision_id=None,
            authority_binding_id=None,
        )
        observed_bytes = source.verbatim_entry.encode("utf-8")
        item = CourseReferenceAuthorityQueueItem(
            selection=selection,
            resolution=CourseReferenceItemResolution.READY,
            candidate=imported_candidate,
            observations=(
                ObservedCandidateEntry(
                    observation_id=source.observation_id,
                    source_id=source.source_id,
                    asserted_source_revision=source.asserted_source_revision,
                    bibliography_sha256=source.bibliography_sha256,
                    bibliography_byte_size=source.bibliography_byte_size,
                    entry_index=source.entry_index,
                    observed_citekey=source.observed_citekey,
                    entry_sha256=hashlib.sha256(observed_bytes).hexdigest(),
                    entry_byte_size=len(observed_bytes),
                ),
            ),
            rendered_entry=RenderedCandidateEntryEvidence(
                entry_id=rendered.entry_id,
                citekey=rendered.citekey,
                entry_type=rendered.entry_type,
                normalized_fields=rendered.normalized_fields,
                source_observation_ids=rendered.source_observation_ids,
                rendered_sha256=hashlib.sha256(
                    rendered.rendered_entry
                ).hexdigest(),
                rendered_byte_size=len(rendered.rendered_entry),
            ),
            record_matches=(),
            assets=(),
            current_identity_decisions=(),
            current_asset_decision=None,
            active_authority=authority,
            allowed_identity_actions=(),
            allowed_asset_actions=(),
        )
        items.append(item)
        authorities.append(authority)
        projection_ids.append(projection_id)
    return CourseReferenceAuthorityQueue(
        request_id=_cid("course-reference-authority-queue-request", "request"),
        scope=scope,
        scope_id=scope.scope_id,
        course_id=scope.course_id,
        items=tuple(items),
        active_authorities=tuple(authorities),
        source_export_result_id=render.source_export_result_id,
        render_result_id=render.result_id,
        review_projection_id=_cid("review-projection", "review"),
        state_projection_ids=tuple(sorted(projection_ids)),
    )


def _candidates(
    render: CandidateBibliographyRenderResult,
) -> tuple[ReferenceCandidate, ...]:
    values: list[ReferenceCandidate] = []
    for entry in render.entries:
        fields = dict(entry.normalized_fields)
        values.append(
            ReferenceCandidate.create(
                proposed_citekey=entry.citekey,
                entry_type=entry.entry_type,
                title=fields.get("title"),
                authors=(fields["author"],) if "author" in fields else (),
                year=fields.get("year"),
                doi=fields.get("doi"),
                isbn=fields.get("isbn"),
                url=fields.get("url"),
                eprint=fields.get("eprint"),
                source_observation_ids=entry.source_observation_ids,
                generator=ProducerIdentity("selected-render-test", "1"),
            )
        )
    return tuple(values)


def _selected_input(
    *,
    item: CourseReferenceAuthorityQueueItem,
    ordinal: int,
) -> CourseReferenceSelectedBibliographySelection:
    assert item.candidate is not None
    assert item.active_authority is not None
    return CourseReferenceSelectedBibliographySelection(
        new_ordinal=ordinal,
        predecessor_selection_id=item.selection.selection_id,
        predecessor_locator_binding_id=item.selection.locator_binding_id,
        reference_locator=item.selection.reference_locator,
        display_citekey=item.selection.display_citekey,
        display_citekey_status=item.selection.display_citekey_status,
        expected_candidate_id=item.candidate.candidate_id,
        expected_current_authority_projection_id=(
            item.active_authority.state_projection_id
        ),
    )


def _request(
    render: CandidateBibliographyRenderResult,
    queue: CourseReferenceAuthorityQueue,
) -> CourseReferenceSelectedBibliographyProjectionRequest:
    retained = (queue.items[0], queue.items[2])
    selections = tuple(
        _selected_input(item=item, ordinal=ordinal)
        for ordinal, item in enumerate(retained, start=1)
    )
    omitted = queue.items[1].selection
    return CourseReferenceSelectedBibliographyProjectionRequest(
        course_id=queue.course_id,
        revised_manifest_id=_cid("course-authoring-manifest", "revised"),
        revised_manifest_sha256=hashlib.sha256(b"revised").hexdigest(),
        predecessor_scope_id=queue.scope_id,
        expected_predecessor_queue_id=queue.queue_id,
        expected_total=2,
        selections=selections,
        omission=CourseReferenceSelectedBibliographyOmission(
            predecessor_ordinal=omitted.ordinal,
            predecessor_selection_id=omitted.selection_id,
            predecessor_locator_binding_id=omitted.locator_binding_id,
            reference_locator=omitted.reference_locator,
            display_citekey=omitted.display_citekey,
            display_citekey_status=omitted.display_citekey_status,
        ),
        artifact_root_alias="private-course",
        artifact_relative_path="generated/references.bib",
        predecessor_queue=queue,
        original_render=render,
    )


def test_action__emits_exact_ordered_private_handoff(tmp_path: Path) -> None:
    render = _render(tmp_path)
    queue = _queue(render)
    request = _request(render, queue)

    result = CourseReferenceSelectedBibliographyProjectionActionizer().action(
        request=request
    )

    assert result.status == COURSE_REFERENCE_SELECTED_BIBLIOGRAPHY_STATUS
    assert result.expected_total == 2
    assert tuple(item.display_citekey for item in result.items) == (
        queue.items[0].selection.display_citekey,
        queue.items[2].selection.display_citekey,
    )
    assert queue.items[1].selection.display_citekey.encode() not in (
        result.bibliography
    )
    assert result.bibliography == (
        render.entries[0].rendered_entry
        + b"\n\n"
        + render.entries[2].rendered_entry
        + b"\n"
    )
    manifest = json.loads(result.manifest_json)
    assert manifest["request_id"] == request.request_id
    assert manifest["expected_total"] == 2
    assert manifest["artifact"] == {
        "byte_size": len(result.bibliography),
        "relative_path": "generated/references.bib",
        "root_alias": "private-course",
        "sha256": result.bibliography_sha256,
    }
    assert [item["reference_locator"] for item in manifest["items"]] == [
        request.selections[0].reference_locator,
        request.selections[1].reference_locator,
    ]
    assert all(
        item.current_authority_projection_id in queue.state_projection_ids
        for item in result.items
    )

    alternate_queue = replace(
        queue,
        request_id=_cid(
            "course-reference-authority-queue-request",
            "alternate-runtime-evidence",
        ),
    )
    assert alternate_queue.queue_id != queue.queue_id
    alternate_request = replace(
        request,
        predecessor_queue=alternate_queue,
        expected_predecessor_queue_id=alternate_queue.queue_id,
    )
    alternate = (
        CourseReferenceSelectedBibliographyProjectionActionizer().action(
            request=alternate_request
        )
    )
    assert alternate.request_id == result.request_id
    assert alternate.result_id == result.result_id
    assert alternate.manifest_json == result.manifest_json
    assert alternate.bibliography == result.bibliography
    assert alternate.execution_predecessor_queue_id != (
        result.execution_predecessor_queue_id
    )


def test_action__fails_closed_on_reorder_or_authority_mismatch(
    tmp_path: Path,
) -> None:
    render = _render(tmp_path)
    queue = _queue(render)
    request = _request(render, queue)
    stale_gate = replace(
        request,
        expected_predecessor_queue_id=_cid(
            "course-reference-authority-queue",
            "stale",
        ),
    )
    with pytest.raises(
        CourseReferenceAuthorityError,
        match="predecessor queue is stale",
    ):
        CourseReferenceSelectedBibliographyProjectionActionizer().action(
            request=stale_gate
        )

    reversed_selections = tuple(
        replace(item, new_ordinal=ordinal)
        for ordinal, item in enumerate(reversed(request.selections), start=1)
    )
    reordered = replace(request, selections=reversed_selections)
    with pytest.raises(
        CourseReferenceAuthorityError,
        match="incomplete or reordered",
    ):
        CourseReferenceSelectedBibliographyProjectionActionizer().action(
            request=reordered
        )

    first = queue.items[0]
    assert first.active_authority is not None
    mismatched_authority = replace(
        first.active_authority,
        candidate_id=_cid("reference-candidate", "wrong"),
    )
    stale_item = replace(first, active_authority=mismatched_authority)
    stale_queue = replace(queue, items=(stale_item, *queue.items[1:]))
    stale_request = replace(
        request,
        predecessor_queue=stale_queue,
        expected_predecessor_queue_id=stale_queue.queue_id,
    )
    with pytest.raises(
        CourseReferenceAuthorityError,
        match="authority candidate is stale",
    ):
        CourseReferenceSelectedBibliographyProjectionActionizer().action(
            request=stale_request
        )
