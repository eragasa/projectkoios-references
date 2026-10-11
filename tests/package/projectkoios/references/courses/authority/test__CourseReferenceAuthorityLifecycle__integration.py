"""End-to-end compatibility tests for course reference authority."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyExportRequest,
    CandidateBibliographyRenderedEntry,
    CandidateBibliographyRenderer,
    CandidateBibliographyRenderRequest,
    CandidateBibliographyRenderResult,
    CandidateBibliographySourceDeclaration,
)
from projectkoios.references.catalog import (
    CatalogConflictError,
    ReferenceCatalog,
)
from projectkoios.references.courses.authority.evidence import (
    IngestionArtifactAuthorityLink,
    ReferenceAssetAuthorityEvidence,
    ReferenceAssetAuthorityEvidenceActionizer,
    ReferenceAssetAuthorityEvidenceRequest,
    ReferenceRecordDiscrepancy,
    ReferenceRecordMatchKind,
    RenderedEntryCandidateBinding,
    RuntimeAssetAvailability,
)
from projectkoios.references.courses.authority.identity_preview import (
    ReferenceIdentityDecisionPreviewRequest,
)
from projectkoios.references.courses.authority.persistence import (
    AppendCanonicalAssetDecisionRequest,
    AppendReferenceIdentityDecisionRequest,
    CanonicalAssetDecisionAppendActionizer,
    ReferenceIdentityDecisionAppendActionizer,
)
from projectkoios.references.courses.authority.plans import (
    CanonicalAssetCompetitorDisposition,
    CanonicalAssetDecisionPreview,
    CanonicalAssetEvidencePlan,
    ReferenceIdentityDecisionPreview,
)
from projectkoios.references.courses.authority.queue import (
    CourseReferenceAuthorityProjector,
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueRequest,
    CourseReferenceItemResolution,
)
from projectkoios.references.courses.authority.reviewed_projection import (
    ReviewedCourseReferenceProjectionActionizer,
    ReviewedCourseReferenceProjectionRequest,
)
from projectkoios.references.courses.authority.scope import (
    CourseDisplayCitekeyStatus,
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceRole,
    CourseReferenceSelectionEvidence,
    CourseReferenceSelectionOrigin,
)
from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionActionizer,
    SearchReferenceAuthorityProjectionRequest,
)
from projectkoios.references.courses.authority.service import (
    CourseReferenceAuthorityEvidenceLoadRequest,
    CourseReferenceAuthorityEvidenceLoadResult,
    CourseReferenceAuthorityFailureReason,
    CourseReferenceAuthorityServiceError,
)
from projectkoios.references.courses.runtime.configuration import (
    CourseReferenceAuthorityAssetRoot,
    CourseReferenceAuthorityBibliographySource,
    CourseReferenceAuthorityRuntimeConfiguration,
)
from projectkoios.references.courses.runtime.facade import (
    FilesystemCourseReferenceAuthorityRuntimeCreateActionizer,
    FilesystemCourseReferenceAuthorityRuntimeCreateRequest,
    FilesystemCourseReferenceAuthorityRuntimeCreateResult,
)
from projectkoios.references.courses.runtime.filesystem import (
    FilesystemCourseReferenceAuthorityEvidenceLoadActionizer,
)
from projectkoios.references.courses.transport.asset import (
    CanonicalAssetPreviewTransportRequest,
    CanonicalAssetPutTransportRequest,
)
from projectkoios.references.courses.transport.identity import (
    ReferenceIdentityPreviewTransportRequest,
    ReferenceIdentityPutTransportRequest,
)
from projectkoios.references.courses.transport.queue import (
    CourseReferenceQueueTransportRequest,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import RootStorageClass
from projectkoios.references.review import (
    CanonicalAssetDecision,
    ReferenceIdentityDecision,
    ReviewActorKind,
    ReviewActorProvenance,
    ReviewAuthorityScope,
    replay_review_records,
)

_FIXTURE = (
    Path(__file__).parents[5]
    / "fixtures"
    / "candidate-bibliography"
    / "render-specials.bib"
)


def _transport_body(body_json: str) -> dict[object, object]:
    """Decode one transport result only for HTTP-shape assertions."""
    value: object = json.loads(body_json)
    assert isinstance(value, dict)
    return value


def _transport_string(body: dict[object, object], key: str) -> str:
    """Return one required string field from an asserted transport object."""
    value = body[key]
    assert isinstance(value, str)
    return value


def _cid(kind: str, value: str) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    kind
        Typed input governed by the function annotation.
    value
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"{kind}:sha256:{digest}"


def _locator_binding_id(
    *,
    ordinal: int,
    display_citekey: str,
    display_status: CourseDisplayCitekeyStatus,
    reference_locator: str,
) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    ordinal
        Typed input governed by the function annotation.
    display_citekey
        Typed input governed by the function annotation.
    display_status
        Typed input governed by the function annotation.
    reference_locator
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    payload = {
        "contract_version": "1.0",
        "display_citekey": display_citekey,
        "display_citekey_status": display_status.value,
        "ordinal": ordinal,
        "reference_locator": reference_locator,
        "reference_owner": "projectkoios-references",
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return f"course-reference-locator-binding:sha256:{digest}"


type FixtureEvidence = tuple[
    CourseReferenceAuthorityQueueRequest,
    tuple[ReferenceCandidate, ...],
    tuple[SourceBibliographyObservation, ...],
]


def _candidate_for_entry(
    entry: CandidateBibliographyRenderedEntry,
) -> ReferenceCandidate:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    entry
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    fields = dict(entry.normalized_fields)
    return ReferenceCandidate.create(
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
        generator=ProducerIdentity("sanitized-candidate-normalizer", "1"),
    )


def _evidence_from_render(
    render: CandidateBibliographyRenderResult,
    *,
    missing_last_binding: bool = False,
) -> FixtureEvidence:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    render
        Typed input governed by the function annotation.
    missing_last_binding
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    observations = tuple(
        observation
        for source in render.request.source.sources
        for observation in source.observations
    )
    candidates = tuple(_candidate_for_entry(entry) for entry in render.entries)
    bindings = tuple(
        RenderedEntryCandidateBinding(
            reference_locator=entry.entry_id,
            rendered_entry_id=entry.entry_id,
            candidate_id=candidate.candidate_id,
            source_observation_ids=entry.source_observation_ids,
        )
        for entry, candidate in zip(render.entries, candidates, strict=True)
    )
    if missing_last_binding:
        bindings = bindings[:-1]
    manifest_id = _cid("course-authoring-manifest", "manifest")
    inventory_id = _cid("course-source-inventory", "inventory")
    scope_id = _cid("course-reference-resolution-scope", "scope")
    selection_ids = tuple(
        _cid("course-reference-selection", f"selection-{index}")
        for index in range(1, len(render.entries) + 1)
    )
    scope = CourseReferenceResolutionScopeEvidence(
        scope_id=scope_id,
        course_id="synthetic-course",
        course_title="Synthetic Solid State Course",
        manifest_id=manifest_id,
        manifest_sha256=hashlib.sha256(b"manifest").hexdigest(),
        inventory_id=inventory_id,
        total=len(selection_ids),
        ordered_selection_ids=selection_ids,
    )
    display_status = CourseDisplayCitekeyStatus.PROPOSED_NONCANONICAL
    selections = tuple(
        CourseReferenceSelectionEvidence(
            scope_id=scope_id,
            selection_id=selection_id,
            locator_binding_id=_locator_binding_id(
                ordinal=ordinal,
                display_citekey=entry.citekey,
                display_status=display_status,
                reference_locator=entry.entry_id,
            ),
            course_id=scope.course_id,
            manifest_id=manifest_id,
            inventory_id=inventory_id,
            ordinal=ordinal,
            origin=CourseReferenceSelectionOrigin.DIRECTED_REFERENCE_SCOPE,
            role=CourseReferenceRole.MANUSCRIPT_BIBLIOGRAPHY,
            display_citekey=entry.citekey,
            display_citekey_status=display_status,
            reference_locator=entry.entry_id,
        )
        for ordinal, (selection_id, entry) in enumerate(
            zip(selection_ids, render.entries, strict=True),
            start=1,
        )
    )
    first = render.entries[0]
    records = (
        ReferenceRecordDiscrepancy(
            citekey=first.citekey,
            bibtex_entry=first.rendered_entry.decode(),
        ),
        ReferenceRecordDiscrepancy(
            citekey=first.citekey,
            bibtex_entry=observations[0].verbatim_entry,
        ),
    )
    request = CourseReferenceAuthorityQueueRequest(
        scope=scope,
        selections=selections,
        render_result=render,
        candidates=candidates,
        rendered_candidate_bindings=bindings,
        record_discrepancies=records,
        assets=(),
        review_projection=replay_review_records((), ()),
        state_projections=(),
    )
    return (request, candidates, observations)


# The base fixture includes resolved and unresolved selections to prove the
# queue remains a Courses-ordered left projection.
def _evidence() -> FixtureEvidence:
    """Evaluate one internal trust-boundary operation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    content = _FIXTURE.read_bytes()
    imported = load_bibliography(
        _FIXTURE,
        source_id="sanitized-test:course-authority",
        source_revision=f"sha256:{hashlib.sha256(content).hexdigest()}",
        source_path="fixtures/render-specials.bib",
        storage_class=RootStorageClass.LOCAL,
    )
    declaration = CandidateBibliographySourceDeclaration(
        collection_id="materials-course",
        observations=imported.observations,
    )
    render = CandidateBibliographyRenderer().render(
        request=CandidateBibliographyRenderRequest(
            source=CandidateBibliographyExportRequest(sources=(declaration,))
        )
    )
    return _evidence_from_render(render)


def _fourteen_evidence(
    tmp_path: Path, *, missing_last_binding: bool = False
) -> FixtureEvidence:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.
    missing_last_binding
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    path = tmp_path / "scope.bib"
    path.write_text(
        "\n\n".join(
            f"@book{{scopeExample{index:02d}, "
            f"title={{Scope Example {index}}}, year={{2026}}}}"
            for index in range(1, 15)
        )
        + "\n",
        encoding="utf-8",
    )
    content = path.read_bytes()
    imported = load_bibliography(
        path,
        source_id="sanitized-test:fourteen-scope",
        source_revision=f"sha256:{hashlib.sha256(content).hexdigest()}",
        source_path="fixtures/scope.bib",
        storage_class=RootStorageClass.LOCAL,
    )
    render = CandidateBibliographyRenderer().render(
        request=CandidateBibliographyRenderRequest(
            source=CandidateBibliographyExportRequest(
                sources=(
                    CandidateBibliographySourceDeclaration(
                        collection_id="fourteen-scope",
                        observations=imported.observations,
                    ),
                )
            )
        )
    )
    return _evidence_from_render(
        render,
        missing_last_binding=missing_last_binding,
    )


def _actor(scope: ReviewAuthorityScope) -> ReviewActorProvenance:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    scope
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    return ReviewActorProvenance(
        actor_id="fixture-curator",
        actor_kind=ReviewActorKind.PERSON,
        authority_scope=scope,
        authority_domain="projectkoios-references",
        verification_record_id=_cid("actor-verification", scope.value),
        verification_method="sanitized-fixture",
    )


def _queue(
    request: CourseReferenceAuthorityQueueRequest,
) -> CourseReferenceAuthorityQueue:
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
    return CourseReferenceAuthorityProjector().action(request=request)


def _catalog(path: Path) -> ReferenceCatalog:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    catalog = ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)
    catalog.initialize()
    return catalog


def _identity_preview(
    queue: CourseReferenceAuthorityQueue,
    *,
    disposition: ReferenceIdentityDecision = (
        ReferenceIdentityDecision.ACCEPT_NEW
    ),
) -> ReferenceIdentityDecisionPreview:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    queue
        Typed input governed by the function annotation.
    disposition
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    item = queue.items[0]
    assert item.candidate is not None
    return ReferenceIdentityDecisionPreview(
        queue=queue,
        selection_id=item.selection.selection_id,
        disposition=disposition,
        target_state_projection_id=None,
        canonical_citekey=(
            item.candidate.proposed_citekey
            if disposition is ReferenceIdentityDecision.ACCEPT_NEW
            else None
        ),
        alias_citekeys=(),
        selected_record_match_ids=tuple(
            sorted(match.record_id for match in item.record_matches)
        ),
        expected_current_decision_id=None,
    )


# Queue tests focus first on preservation: missing References evidence must not
# erase or reorder a Courses-owned selection.
def test__queue__retains_complete_scope_and_left_projects_unresolved(
    tmp_path: Path,
) -> None:
    """Verify the named owner contract behavior.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    complete = _fourteen_evidence(tmp_path)
    complete_queue = _queue(complete[0])
    assert len(complete_queue.items) == 14
    assert all(
        item.resolution is CourseReferenceItemResolution.READY
        for item in complete_queue.items
    )
    assert tuple(
        item.selection.selection_id for item in complete_queue.items
    ) == (complete[0].scope.ordered_selection_ids)

    incomplete = _fourteen_evidence(tmp_path, missing_last_binding=True)
    incomplete_queue = _queue(incomplete[0])
    assert len(incomplete_queue.items) == 14
    assert incomplete_queue.items[-1].resolution is (
        CourseReferenceItemResolution.CANDIDATE_UNAVAILABLE
    )
    assert incomplete_queue.items[-1].allowed_identity_actions == ()

    with pytest.raises(ValueError, match="complete Courses scope envelope"):
        CourseReferenceAuthorityQueueRequest(
            scope=complete[0].scope,
            selections=complete[0].selections[:-1],
            render_result=complete[0].render_result,
            candidates=complete[0].candidates,
            rendered_candidate_bindings=(
                complete[0].rendered_candidate_bindings
            ),
            record_discrepancies=(),
            assets=(),
            review_projection=complete[0].review_projection,
            state_projections=(),
        )


def test__queue__is_path_byte_free_and_revalidates_mutated_binding() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    queue = _queue(evidence[0])
    item = queue.items[0]
    assert queue.control_class == "CONTROL"
    assert item.resolution is CourseReferenceItemResolution.READY
    assert {match.kind for match in item.record_matches} == {
        ReferenceRecordMatchKind.EXACT_OBSERVED_KEY_AND_BYTES,
        ReferenceRecordMatchKind.EXACT_RENDERED_KEY_AND_BYTES,
    }
    assert not hasattr(item.observations[0], "source_path")
    assert not hasattr(item.observations[0], "verbatim_entry")
    assert not hasattr(item.rendered_entry, "rendered_entry")
    assert not hasattr(item.record_matches[0], "bibtex_entry")
    assert "fixtures/render-specials.bib" not in repr(queue)
    with pytest.raises(ValueError, match="not completely reviewed"):
        ReviewedCourseReferenceProjectionActionizer().action(
            request=ReviewedCourseReferenceProjectionRequest(queue=queue)
        )

    object.__setattr__(
        evidence[0].selections[0],
        "locator_binding_id",
        _cid("course-reference-locator-binding", "mutated"),
    )
    with pytest.raises(ValueError, match="locator binding"):
        _queue(evidence[0])

    binding_evidence = _evidence()
    object.__setattr__(
        binding_evidence[0].rendered_candidate_bindings[0],
        "candidate_id",
        _cid("reference-candidate", "mutated"),
    )
    with pytest.raises(ValueError, match="request revision is stale"):
        _queue(binding_evidence[0])


def test__candidate_resolution__uses_explicit_binding_not_citekey_join() -> (
    None
):
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    candidate = evidence[1][0]
    changed = ReferenceCandidate.create(
        proposed_citekey="changedDisplayKey",
        entry_type=candidate.entry_type,
        title=candidate.title,
        authors=candidate.authors,
        year=candidate.year,
        source_observation_ids=candidate.source_observation_ids,
        generator=candidate.generator,
    )
    binding = RenderedEntryCandidateBinding(
        reference_locator=evidence[0].render_result.entries[0].entry_id,
        rendered_entry_id=evidence[0].render_result.entries[0].entry_id,
        candidate_id=changed.candidate_id,
        source_observation_ids=changed.source_observation_ids,
    )
    request = CourseReferenceAuthorityQueueRequest(
        scope=evidence[0].scope,
        selections=evidence[0].selections,
        render_result=evidence[0].render_result,
        candidates=(changed,),
        rendered_candidate_bindings=(binding,),
        record_discrepancies=(),
        assets=(),
        review_projection=evidence[0].review_projection,
        state_projections=(),
    )
    item = _queue(request).items[0]
    assert item.candidate == changed
    assert item.resolution is (
        CourseReferenceItemResolution.CANDIDATE_DISPLAY_GUARD_MISMATCH
    )
    assert item.allowed_identity_actions == ()

    same_key_other = ReferenceCandidate.create(
        proposed_citekey=candidate.proposed_citekey,
        entry_type=candidate.entry_type,
        title="A distinct candidate with the same display key",
        authors=candidate.authors,
        year=candidate.year,
        source_observation_ids=candidate.source_observation_ids,
        generator=candidate.generator,
    )
    same_key_binding = RenderedEntryCandidateBinding(
        reference_locator=evidence[0].render_result.entries[0].entry_id,
        rendered_entry_id=evidence[0].render_result.entries[0].entry_id,
        candidate_id=same_key_other.candidate_id,
        source_observation_ids=same_key_other.source_observation_ids,
    )
    same_key_request = CourseReferenceAuthorityQueueRequest(
        scope=evidence[0].scope,
        selections=evidence[0].selections,
        render_result=evidence[0].render_result,
        candidates=(candidate, same_key_other),
        rendered_candidate_bindings=(same_key_binding,),
        record_discrepancies=(),
        assets=(),
        review_projection=evidence[0].review_projection,
        state_projections=(),
    )
    same_key_item = _queue(same_key_request).items[0]
    assert same_key_item.resolution is CourseReferenceItemResolution.READY
    assert same_key_item.candidate == same_key_other


# Identity tests keep preview, append, replay, and retry in one scenario so a
# false success cannot hide a partially persisted transition.
def test__identity_preview_append_is_atomic_retryable_and_defer_is_contextual(
    tmp_path: Path,
) -> None:
    """Verify the named owner contract behavior.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    queue = _queue(evidence[0])
    catalog = _catalog(tmp_path / "references.sqlite3")
    appender = ReferenceIdentityDecisionAppendActionizer(
        catalog=catalog,
        candidates=evidence[1],
        observations=evidence[2],
    )
    preview = _identity_preview(queue)
    request = AppendReferenceIdentityDecisionRequest(
        preview=preview,
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="Accept the exact explicit identity preview.",
        decided_at="2026-09-20T12:00:00Z",
    )
    result = appender.action(request=request)
    assert appender.action(request=request) == result
    assert catalog.read_candidates() == evidence[1]
    assert catalog.counts()["human_review_decisions"] == 1
    assert catalog.counts()["state_projections"] == 1

    defer_catalog = _catalog(tmp_path / "defer.sqlite3")
    defer_queue = _queue(evidence[0])
    defer_result = ReferenceIdentityDecisionAppendActionizer(
        catalog=defer_catalog,
        candidates=evidence[1],
        observations=evidence[2],
    ).action(
        request=AppendReferenceIdentityDecisionRequest(
            preview=_identity_preview(
                defer_queue,
                disposition=ReferenceIdentityDecision.DEFER,
            ),
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Defer only for this course.",
            decided_at="2026-09-20T12:00:00Z",
        )
    )
    assert defer_result.decision.context_id == evidence[0].scope.course_id
    assert defer_result.state_projection is None


def test__stale_preview_rolls_back_candidate_and_decision(
    tmp_path: Path,
) -> None:
    """Verify the named owner contract behavior.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    queue = _queue(evidence[0])
    catalog = _catalog(tmp_path / "references.sqlite3")
    appender = ReferenceIdentityDecisionAppendActionizer(
        catalog=catalog,
        candidates=evidence[1],
        observations=evidence[2],
    )
    first = AppendReferenceIdentityDecisionRequest(
        preview=_identity_preview(queue),
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="First decision.",
        decided_at="2026-09-20T12:00:00Z",
    )
    stale = AppendReferenceIdentityDecisionRequest(
        preview=_identity_preview(queue),
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="Competing stale decision.",
        decided_at="2026-09-20T12:00:01Z",
    )
    accepted = appender.action(request=first)
    with pytest.raises(CatalogConflictError, match="revision is stale"):
        appender.action(request=stale)
    assert catalog.read_review_projection().human_decision_history == (
        accepted.decision,
    )


# Asset fixtures intentionally carry exact typed Ingestion linkage rather than
# flattened provenance strings.
def _asset_evidence(
    asset: SourceAssetRecord,
    *,
    runtime_token: str,
) -> ReferenceAssetAuthorityEvidence:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    asset
        Typed input governed by the function annotation.
    runtime_token
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    base = (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(request=ReferenceAssetAuthorityEvidenceRequest(asset=asset))
        .evidence
    )
    link = IngestionArtifactAuthorityLink(
        asset_observation_id=base.asset_observation_id,
        source_id="source:book",
        document_id=(
            "reading-evidence-document:sha256:"
            "8a7358d8dafbf7da3d58f6b3233c9db0284f4ee0ec7d4891da1106bfd7942871"
        ),
        artifact_verification_result_id=(
            "managed-artifact-verification-result:sha256:"
            "5c68aeb1065e4215cbfb07e12dcb0b54329a1010a58c04bb54d39d3469b60be0"
        ),
    )
    return (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(
            request=ReferenceAssetAuthorityEvidenceRequest(
                asset=asset,
                runtime_availability=RuntimeAssetAvailability.AVAILABLE,
                runtime_evidence_id=_cid(
                    "runtime-asset-evidence", runtime_token
                ),
                document_binding_ids=(
                    _cid("document-source-binding", "binding"),
                ),
                ingestion_evidence_ids=(
                    _cid("ingestion-evidence", "ingested"),
                ),
                ingestion_artifact_links=(link,),
            )
        )
        .evidence
    )


def test__ingestion_link__accepts_exact_opaque_source_identity() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    first = IngestionArtifactAuthorityLink(
        asset_observation_id=_cid("source-asset-observation", "asset"),
        source_id="source:book",
        document_id=(
            "reading-evidence-document:sha256:"
            "8a7358d8dafbf7da3d58f6b3233c9db0284f4ee0ec7d4891da1106bfd7942871"
        ),
        artifact_verification_result_id=(
            "managed-artifact-verification-result:sha256:"
            "5c68aeb1065e4215cbfb07e12dcb0b54329a1010a58c04bb54d39d3469b60be0"
        ),
    )
    second = IngestionArtifactAuthorityLink(
        asset_observation_id=first.asset_observation_id,
        source_id="source:other-book",
        document_id=first.document_id,
        artifact_verification_result_id=(first.artifact_verification_result_id),
    )
    assert first.source_id == "source:book"
    assert first.link_id != second.link_id
    with pytest.raises(ValueError, match="nonempty Ingestion identity"):
        IngestionArtifactAuthorityLink(
            asset_observation_id=first.asset_observation_id,
            source_id="",
            document_id=first.document_id,
            artifact_verification_result_id=(
                first.artifact_verification_result_id
            ),
        )
    with pytest.raises(ValueError, match="Ingestion identity limit"):
        IngestionArtifactAuthorityLink(
            asset_observation_id=first.asset_observation_id,
            source_id="x" * 1_025,
            document_id=first.document_id,
            artifact_verification_result_id=(
                first.artifact_verification_result_id
            ),
        )


# Asset authority and Search admission are tested together because Search must
# fail closed when any current runtime/linkage predicate is absent.
def test__asset_plan_and_search_require_typed_ingestion_linkage(
    tmp_path: Path,
) -> None:
    """Verify the named owner contract behavior.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    catalog = _catalog(tmp_path / "references.sqlite3")
    appender = ReferenceIdentityDecisionAppendActionizer(
        catalog=catalog,
        candidates=evidence[1],
        observations=evidence[2],
    )
    identity = appender.action(
        request=AppendReferenceIdentityDecisionRequest(
            preview=_identity_preview(_queue(evidence[0])),
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Accept identity only.",
            decided_at="2026-09-20T12:00:00Z",
        )
    )
    candidate = evidence[1][0]
    asset = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256="a" * 64,
        byte_size=42,
        root_alias="private-library",
        relative_path="opaque.pdf",
        rights_status="rights-not-assessed",
        asset_status="managed-private-integrity-validated-source",
    )
    competitor = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256="c" * 64,
        byte_size=43,
        root_alias="private-library",
        relative_path="competitor.pdf",
        rights_status="rights-not-assessed",
        asset_status="observed-source-copy",
    )
    catalog.record_source_asset(asset)
    catalog.record_source_asset(competitor)
    asset_evidence = _asset_evidence(asset, runtime_token="available")
    competitor_evidence = _asset_evidence(
        competitor,
        runtime_token="competitor",
    )
    request = CourseReferenceAuthorityQueueRequest(
        scope=evidence[0].scope,
        selections=evidence[0].selections,
        render_result=evidence[0].render_result,
        candidates=evidence[1],
        rendered_candidate_bindings=evidence[0].rendered_candidate_bindings,
        record_discrepancies=evidence[0].record_discrepancies,
        assets=(asset_evidence, competitor_evidence),
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
    )
    queue = _queue(request)
    item = queue.items[0]
    assert item.active_authority is not None
    plan = CanonicalAssetEvidencePlan(
        queue=queue,
        selection_id=item.selection.selection_id,
        identity_state_projection_id=item.active_authority.state_projection_id,
        assets=item.assets,
    )
    with pytest.raises(ValueError, match="every competitor"):
        CanonicalAssetDecisionPreview(
            plan=plan,
            disposition=CanonicalAssetDecision.AUTHORIZE,
            competitor_dispositions=(
                CanonicalAssetCompetitorDisposition(
                    asset_observation_id=(asset_evidence.asset_observation_id),
                    disposition=CanonicalAssetDecision.AUTHORIZE,
                    rationale="Incomplete competitor plan.",
                ),
            ),
            expected_current_decision_id=None,
        )
    preview = CanonicalAssetDecisionPreview(
        plan=plan,
        disposition=CanonicalAssetDecision.AUTHORIZE,
        competitor_dispositions=(
            CanonicalAssetCompetitorDisposition(
                asset_observation_id=asset_evidence.asset_observation_id,
                disposition=CanonicalAssetDecision.AUTHORIZE,
                rationale="Select exact verified competitor.",
            ),
            CanonicalAssetCompetitorDisposition(
                asset_observation_id=(competitor_evidence.asset_observation_id),
                disposition=CanonicalAssetDecision.REJECT,
                rationale="Reject the nonselected duplicate competitor.",
            ),
        ),
        expected_current_decision_id=None,
    )
    asset_result = CanonicalAssetDecisionAppendActionizer(
        catalog=catalog,
        candidates=evidence[1],
        observations=evidence[2],
    ).action(
        request=AppendCanonicalAssetDecisionRequest(
            preview=preview,
            actor=_actor(ReviewAuthorityScope.CANONICAL_ASSET_CURATOR),
            rationale="Authorize linkage; rights remain unassessed.",
            decided_at="2026-09-20T12:01:00Z",
        )
    )
    unlinked_asset_evidence = (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(
            request=ReferenceAssetAuthorityEvidenceRequest(
                asset=asset,
                runtime_availability=RuntimeAssetAvailability.AVAILABLE,
                runtime_evidence_id=_cid("runtime-asset-evidence", "unlinked"),
            )
        )
        .evidence
    )
    without_link = SearchReferenceAuthorityProjectionActionizer().action(
        request=SearchReferenceAuthorityProjectionRequest(
            review_projection=catalog.read_review_projection(),
            state_projections=catalog.read_state_projections(),
            asset_evidence=(unlinked_asset_evidence,),
        )
    )
    assert without_link.bindings == ()
    mismatched_link = IngestionArtifactAuthorityLink(
        asset_observation_id=asset_evidence.asset_observation_id,
        source_id="source:other-book",
        document_id=(
            "reading-evidence-document:sha256:"
            "8a7358d8dafbf7da3d58f6b3233c9db0284f4ee0ec7d4891da1106bfd7942871"
        ),
        artifact_verification_result_id=(
            "managed-artifact-verification-result:sha256:"
            "5c68aeb1065e4215cbfb07e12dcb0b54329a1010a58c04bb54d39d3469b60be0"
        ),
    )
    mismatched_evidence = (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(
            request=ReferenceAssetAuthorityEvidenceRequest(
                asset=asset,
                runtime_availability=RuntimeAssetAvailability.AVAILABLE,
                runtime_evidence_id=asset_evidence.runtime_evidence_id,
                document_binding_ids=asset_evidence.document_binding_ids,
                ingestion_evidence_ids=asset_evidence.ingestion_evidence_ids,
                ingestion_artifact_links=(mismatched_link,),
            )
        )
        .evidence
    )
    assert (
        SearchReferenceAuthorityProjectionActionizer()
        .action(
            request=SearchReferenceAuthorityProjectionRequest(
                review_projection=catalog.read_review_projection(),
                state_projections=catalog.read_state_projections(),
                asset_evidence=(mismatched_evidence,),
            )
        )
        .bindings
        == ()
    )
    stale_runtime_evidence = (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(
            request=ReferenceAssetAuthorityEvidenceRequest(
                asset=asset,
                runtime_availability=RuntimeAssetAvailability.AVAILABLE,
                runtime_evidence_id=_cid("runtime-asset-evidence", "stale"),
                document_binding_ids=asset_evidence.document_binding_ids,
                ingestion_evidence_ids=asset_evidence.ingestion_evidence_ids,
                ingestion_artifact_links=(
                    asset_evidence.ingestion_artifact_links
                ),
            )
        )
        .evidence
    )
    assert (
        SearchReferenceAuthorityProjectionActionizer()
        .action(
            request=SearchReferenceAuthorityProjectionRequest(
                review_projection=catalog.read_review_projection(),
                state_projections=catalog.read_state_projections(),
                asset_evidence=(
                    stale_runtime_evidence,
                    competitor_evidence,
                ),
            )
        )
        .bindings
        == ()
    )
    search = SearchReferenceAuthorityProjectionActionizer().action(
        request=SearchReferenceAuthorityProjectionRequest(
            review_projection=catalog.read_review_projection(),
            state_projections=catalog.read_state_projections(),
            asset_evidence=(asset_evidence, competitor_evidence),
        )
    )
    assert len(search.bindings) == 1
    binding = search.bindings[0]
    assert binding.identity_decision_id == identity.decision.decision_id
    assert (
        binding.canonical_asset_decision_id == asset_result.decision.decision_id
    )
    assert binding.ingestion_artifact_links == (
        asset_evidence.ingestion_artifact_links
    )
    assert binding.ingestion_artifact_links[0].source_id == "source:book"
    assert asset.relative_path not in repr(search)


def test__owner_evidence__requires_consistent_observations() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    with pytest.raises(ValueError, match="differ from render observations"):
        CourseReferenceAuthorityEvidenceLoadResult(
            render_result=evidence[0].render_result,
            candidates=evidence[1],
            observations=(),
            rendered_candidate_bindings=(
                evidence[0].rendered_candidate_bindings
            ),
            record_discrepancies=(),
            assets=(),
        )


def test__filesystem_provider_factory__owns_private_parsing_and_catalog_reads(
    tmp_path: Path,
) -> None:
    """Verify the named owner contract behavior.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    catalog_path = tmp_path / "references.sqlite3"
    _catalog(catalog_path)
    digest = hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    configuration = CourseReferenceAuthorityRuntimeConfiguration(
        course_id=evidence[0].scope.course_id,
        catalog_path=catalog_path,
        catalog_storage_class=RootStorageClass.LOCAL,
        bibliography_sources=(
            CourseReferenceAuthorityBibliographySource(
                collection_id="materials-course",
                bibliography_path=_FIXTURE,
                source_id="sanitized-test:course-authority",
                asserted_source_revision=f"sha256:{digest}",
                source_path="fixtures/render-specials.bib",
                storage_class=RootStorageClass.LOCAL,
            ),
        ),
    )
    assert str(_FIXTURE) not in repr(configuration)
    assert str(catalog_path) not in repr(configuration)
    runtime = (
        FilesystemCourseReferenceAuthorityRuntimeCreateActionizer().action(
            request=FilesystemCourseReferenceAuthorityRuntimeCreateRequest(
                configuration=configuration
            )
        )
    )
    transport = runtime.queue.action(
        request=CourseReferenceQueueTransportRequest(
            scope=evidence[0].scope,
            selections=evidence[0].selections,
        )
    )
    body = _transport_body(transport.body_json)
    items = body["items"]
    assert isinstance(items, list)
    selection_ids: list[object] = []
    resolutions: list[object] = []
    for item in items:
        assert isinstance(item, dict)
        selection = item["selection"]
        assert isinstance(selection, dict)
        selection_ids.append(selection["selection_id"])
        resolutions.append(item["resolution"])
    assert tuple(selection_ids) == evidence[0].scope.ordered_selection_ids
    assert set(resolutions) == {CourseReferenceItemResolution.READY.value}


def test__filesystem_provider__reobserves_asset_and_linkage_evidence(
    tmp_path: Path,
) -> None:
    """Verify the named owner contract behavior.

    Parameters
    ----------
    tmp_path
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    evidence = _evidence()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    asset_path = asset_root / "asset.pdf"
    initial_bytes = b"%PDF-1.7\nfixture\n"
    asset_path.write_bytes(initial_bytes)
    candidate = evidence[1][0]
    raw_asset = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256=hashlib.sha256(initial_bytes).hexdigest(),
        byte_size=len(initial_bytes),
        root_alias="runtime-assets",
        relative_path="asset.pdf",
        rights_status="rights-not-assessed",
        asset_status="observed-source-copy",
    )
    asset_observation_id = (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(request=ReferenceAssetAuthorityEvidenceRequest(asset=raw_asset))
        .evidence.asset_observation_id
    )
    linkage_path = tmp_path / "linkage.json"

    def write_linkage(source_id: str) -> None:
        """Execute the named References-owned operation.

        Parameters
        ----------
        source_id
            Typed input governed by the function annotation.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        linkage_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "assets": [
                        {
                            "asset_observation_id": asset_observation_id,
                            "document_binding_ids": [
                                _cid("document-source-binding", "binding")
                            ],
                            "ingestion_evidence_ids": [
                                _cid("ingestion-evidence", "evidence")
                            ],
                            "ingestion_artifact_links": [
                                {
                                    "source_id": source_id,
                                    "document_id": (
                                        "reading-evidence-document:sha256:"
                                        "8a7358d8dafbf7da3d58f6b3233c9db0"
                                        "284f4ee0ec7d4891da1106bfd7942871"
                                    ),
                                    "artifact_verification_result_id": (
                                        "managed-artifact-verification-result:"
                                        "sha256:5c68aeb1065e4215cbfb07e12dcb0b54"
                                        "329a1010a58c04bb54d39d3469b60be0"
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    write_linkage("source:book")
    digest = hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    provider = FilesystemCourseReferenceAuthorityEvidenceLoadActionizer(
        course_id=evidence[0].scope.course_id,
        bibliography_sources=(
            CourseReferenceAuthorityBibliographySource(
                collection_id="materials-course",
                bibliography_path=_FIXTURE,
                source_id="sanitized-test:course-authority",
                asserted_source_revision=f"sha256:{digest}",
                source_path="fixtures/render-specials.bib",
                storage_class=RootStorageClass.LOCAL,
            ),
        ),
        asset_roots=(
            CourseReferenceAuthorityAssetRoot(
                root_alias="runtime-assets",
                root_path=asset_root,
                storage_class=RootStorageClass.LOCAL,
            ),
        ),
        asset_linkage_path=linkage_path,
    )

    def load_asset() -> ReferenceAssetAuthorityEvidence:
        """Execute the named References-owned operation.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        owner = provider.action(
            request=CourseReferenceAuthorityEvidenceLoadRequest(
                scope=evidence[0].scope,
                catalog_candidates=(),
                catalog_observations=(),
                catalog_assets=(raw_asset,),
            )
        )
        assert len(owner.assets) == 1
        return owner.assets[0]

    available = load_asset()
    assert available.runtime_availability is RuntimeAssetAvailability.AVAILABLE
    assert available.ingestion_artifact_links[0].source_id == "source:book"

    asset_path.write_bytes(b"%PDF-1.7\nchanged\n")
    changed = load_asset()
    assert changed.runtime_availability is RuntimeAssetAvailability.UNAVAILABLE
    assert changed.runtime_evidence_id != available.runtime_evidence_id

    asset_path.write_bytes(initial_bytes)
    write_linkage("source:replacement")
    relinked = load_asset()
    assert relinked.runtime_availability is RuntimeAssetAvailability.AVAILABLE
    assert relinked.ingestion_artifact_links[0].source_id == (
        "source:replacement"
    )
    assert relinked.ingestion_artifact_links != (
        available.ingestion_artifact_links
    )

    asset_path.unlink()
    missing = load_asset()
    assert missing.runtime_availability is RuntimeAssetAvailability.UNAVAILABLE
    assert missing.runtime_evidence_id != available.runtime_evidence_id
    assert missing.runtime_evidence_id != changed.runtime_evidence_id


def test__optional_private_exact_fourteen_smoke() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    declaration_file = os.environ.get(
        "PROJECTKOIOS_REFERENCE_AUTHORITY_PRIVATE_SMOKE_JSON"
    )
    if declaration_file is None:
        pytest.skip("private authority smoke declaration is not configured")
    declaration = json.loads(Path(declaration_file).read_text(encoding="utf-8"))
    raw_scope = declaration["scope"]
    raw_selections = raw_scope["selections"]
    selections = tuple(
        CourseReferenceSelectionEvidence(
            scope_id=raw_scope["scope_id"],
            selection_id=item["selection_id"],
            locator_binding_id=item["locator_binding_id"],
            course_id=raw_scope["course_id"],
            manifest_id=raw_scope["manifest_id"],
            inventory_id=raw_scope["inventory_id"],
            ordinal=item["ordinal"],
            origin=CourseReferenceSelectionOrigin(item["origin"]),
            role=CourseReferenceRole(item["role"]),
            display_citekey=item["display_citekey"],
            display_citekey_status=CourseDisplayCitekeyStatus(
                item["display_citekey_status"]
            ),
            reference_locator=item["reference_locator"],
        )
        for item in raw_selections
    )
    scope = CourseReferenceResolutionScopeEvidence(
        scope_id=raw_scope["scope_id"],
        course_id=raw_scope["course_id"],
        course_title=raw_scope["course_title"],
        manifest_id=raw_scope["manifest_id"],
        manifest_sha256=raw_scope["manifest_sha256"],
        inventory_id=raw_scope["inventory_id"],
        total=raw_scope["total"],
        ordered_selection_ids=tuple(item.selection_id for item in selections),
    )
    sources = tuple(
        CourseReferenceAuthorityBibliographySource(
            collection_id=item["collection_id"],
            bibliography_path=Path(item["path"]),
            source_id=item["source_id"],
            asserted_source_revision=item["asserted_source_revision"],
            source_path=item["source_path"],
            storage_class=RootStorageClass(item["storage_class"]),
        )
        for item in declaration["sources"]
    )
    provider = FilesystemCourseReferenceAuthorityEvidenceLoadActionizer(
        course_id=scope.course_id,
        bibliography_sources=sources,
    )
    evidence = provider.action(
        request=CourseReferenceAuthorityEvidenceLoadRequest(
            scope=scope,
            catalog_candidates=(),
            catalog_observations=(),
            catalog_assets=(),
        )
    )
    queue = _queue(
        CourseReferenceAuthorityQueueRequest(
            scope=scope,
            selections=selections,
            render_result=evidence.render_result,
            candidates=evidence.candidates,
            rendered_candidate_bindings=(evidence.rendered_candidate_bindings),
            record_discrepancies=evidence.record_discrepancies,
            assets=evidence.assets,
            review_projection=replay_review_records((), ()),
            state_projections=(),
        )
    )
    assert (
        evidence.render_result.result_id
        == declaration["expected_render_result_id"]
    )
    assert scope.inventory_id == declaration["expected_inventory_id"]
    assert len(queue.items) == declaration["expected_total"] == 14
    assert tuple(item.selection.selection_id for item in queue.items) == (
        scope.ordered_selection_ids
    )
    assert all(
        item.resolution is CourseReferenceItemResolution.READY
        for item in queue.items
    )


def _identity_runtime(
    tmp_path: Path,
    evidence: FixtureEvidence,
) -> tuple[
    CourseReferenceAuthorityRuntimeConfiguration,
    FilesystemCourseReferenceAuthorityRuntimeCreateResult,
]:
    """Create one fresh typed runtime over deterministic fixture evidence."""
    catalog_path = tmp_path / "authority.sqlite3"
    _catalog(catalog_path)
    digest = hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    configuration = CourseReferenceAuthorityRuntimeConfiguration(
        course_id=evidence[0].scope.course_id,
        catalog_path=catalog_path,
        catalog_storage_class=RootStorageClass.LOCAL,
        bibliography_sources=(
            CourseReferenceAuthorityBibliographySource(
                collection_id="materials-course",
                bibliography_path=_FIXTURE,
                source_id="sanitized-test:course-authority",
                asserted_source_revision=f"sha256:{digest}",
                source_path="fixtures/render-specials.bib",
                storage_class=RootStorageClass.LOCAL,
            ),
        ),
    )
    runtime = (
        FilesystemCourseReferenceAuthorityRuntimeCreateActionizer().action(
            request=FilesystemCourseReferenceAuthorityRuntimeCreateRequest(
                configuration=configuration
            )
        )
    )
    return configuration, runtime


def _identity_preview_request(
    queue: CourseReferenceAuthorityQueue,
) -> ReferenceIdentityDecisionPreviewRequest:
    """Build the exact public identity-preview request for the first item."""
    item = queue.items[0]
    assert item.candidate is not None
    return ReferenceIdentityDecisionPreviewRequest(
        scope=queue.scope,
        selections=tuple(entry.selection for entry in queue.items),
        selection_id=item.selection.selection_id,
        disposition=ReferenceIdentityDecision.ACCEPT_NEW,
        target_state_projection_id=None,
        canonical_citekey=item.candidate.proposed_citekey,
        alias_citekeys=(),
        selected_record_match_ids=tuple(
            sorted(match.record_id for match in item.record_matches)
        ),
        expected_current_decision_id=None,
    )


def _identity_transport_preview_request(
    queue: CourseReferenceAuthorityQueue,
    queue_body: dict[object, object],
) -> ReferenceIdentityPreviewTransportRequest:
    """Translate the typed owner fixture into primitive transport input."""
    request = _identity_preview_request(queue)
    items = queue_body["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    return ReferenceIdentityPreviewTransportRequest(
        scope=request.scope,
        selections=request.selections,
        selection_id=request.selection_id,
        expected_queue_id=_transport_string(queue_body, "queue_id"),
        expected_item_revision_id=_transport_string(
            item,
            "item_revision_id",
        ),
        disposition=request.disposition.name,
        target_state_projection_id=request.target_state_projection_id,
        canonical_citekey=request.canonical_citekey,
        alias_citekeys=request.alias_citekeys,
        selected_record_match_ids=(),
        expected_current_decision_id=request.expected_current_decision_id,
    )


def _identity_transport_put_request(
    *,
    preview_request: ReferenceIdentityPreviewTransportRequest,
    preview_body: dict[object, object],
    rationale: str,
    decided_at: str,
    idempotency_key: str,
) -> ReferenceIdentityPutTransportRequest:
    """Bind one primitive PUT to the exact generated preview result."""
    actor = _actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR)
    return ReferenceIdentityPutTransportRequest(
        scope=preview_request.scope,
        selections=preview_request.selections,
        selection_id=preview_request.selection_id,
        idempotency_key=idempotency_key,
        expected_queue_id=_transport_string(preview_body, "queue_id"),
        expected_item_revision_id=_transport_string(
            preview_body,
            "item_revision_id",
        ),
        expected_preview_id=_transport_string(preview_body, "preview_id"),
        expected_preview_result_id=_transport_string(
            preview_body,
            "result_id",
        ),
        expected_current_decision_id=(
            preview_request.expected_current_decision_id
        ),
        disposition=preview_request.disposition,
        target_state_projection_id=(preview_request.target_state_projection_id),
        canonical_citekey=preview_request.canonical_citekey,
        alias_citekeys=preview_request.alias_citekeys,
        selected_record_match_ids=(preview_request.selected_record_match_ids),
        rationale=rationale,
        decided_at=decided_at,
        actor_id=actor.actor_id,
        actor_verification_record_id=actor.verification_record_id,
        actor_verification_method=actor.verification_method,
    )


def test__identity_put__reconstructs_exact_retry_after_runtime_reopen(
    tmp_path: Path,
) -> None:
    """Require restart-safe retry and conflicting-key rejection."""
    evidence = _evidence()
    configuration, runtime = _identity_runtime(tmp_path, evidence)
    queue = _queue(evidence[0])
    queue_body = _transport_body(
        runtime.queue.action(
            request=CourseReferenceQueueTransportRequest(
                scope=evidence[0].scope,
                selections=evidence[0].selections,
            )
        ).body_json
    )
    queue_items = queue_body["items"]
    assert isinstance(queue_items, list)
    queue_item = queue_items[0]
    assert isinstance(queue_item, dict)
    initial_item_revision_id = _transport_string(
        queue_item,
        "item_revision_id",
    )
    preview_request = _identity_transport_preview_request(queue, queue_body)
    preview = runtime.identity_preview.action(request=preview_request)
    preview_body = _transport_body(preview.body_json)
    put_request = _identity_transport_put_request(
        preview_request=preview_request,
        preview_body=preview_body,
        rationale="Accept the exact owner preview.",
        decided_at="2026-09-20T12:00:00Z",
        idempotency_key="identity-retry",
    )
    first = runtime.identity_put.action(request=put_request)
    first_body = _transport_body(first.body_json)
    reopened = (
        FilesystemCourseReferenceAuthorityRuntimeCreateActionizer().action(
            request=FilesystemCourseReferenceAuthorityRuntimeCreateRequest(
                configuration=configuration
            )
        )
    )
    assert reopened.identity_put.action(request=put_request) == first
    assert _transport_string(first_body, "preview_id") == _transport_string(
        preview_body,
        "preview_id",
    )
    assert (
        _transport_string(
            first_body,
            "refreshed_item_revision_id",
        )
        != initial_item_revision_id
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as captured:
        reopened.identity_put.action(
            request=replace(
                put_request,
                rationale="Conflicting reuse of the same idempotency key.",
            )
        )
    assert captured.value.reason is (
        CourseReferenceAuthorityFailureReason.IDEMPOTENCY_CONFLICT
    )
    assert (
        ReferenceCatalog(
            configuration.catalog_path,
            storage_class=configuration.catalog_storage_class,
        ).counts()["human_review_decisions"]
        == 1
    )


def test__identity_put__rejects_stale_preview_without_second_mutation(
    tmp_path: Path,
) -> None:
    """Require a stale public preview to fail before another append."""
    evidence = _evidence()
    configuration, runtime = _identity_runtime(tmp_path, evidence)
    queue = _queue(evidence[0])
    queue_body = _transport_body(
        runtime.queue.action(
            request=CourseReferenceQueueTransportRequest(
                scope=evidence[0].scope,
                selections=evidence[0].selections,
            )
        ).body_json
    )
    preview_request = _identity_transport_preview_request(queue, queue_body)
    preview = runtime.identity_preview.action(request=preview_request)
    preview_body = _transport_body(preview.body_json)
    catalog = ReferenceCatalog(
        configuration.catalog_path,
        storage_class=configuration.catalog_storage_class,
    )
    runtime.identity_put.action(
        request=_identity_transport_put_request(
            preview_request=preview_request,
            preview_body=preview_body,
            rationale="Win the optimistic append race.",
            decided_at="2026-09-20T11:59:59Z",
            idempotency_key="winning-identity",
        )
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as captured:
        runtime.identity_put.action(
            request=_identity_transport_put_request(
                preview_request=preview_request,
                preview_body=preview_body,
                rationale="Lose the optimistic append race.",
                decided_at="2026-09-20T12:00:00Z",
                idempotency_key="stale-identity",
            )
        )
    assert captured.value.reason is (
        CourseReferenceAuthorityFailureReason.REVISION_STALE
    )
    assert catalog.counts()["human_review_decisions"] == 1


def test__asset_put__retries_after_reopen_and_projects_exact_ingestion_link(
    tmp_path: Path,
) -> None:
    """Require atomic asset authority and exact typed Search linkage."""
    evidence = _evidence()
    configuration, runtime = _identity_runtime(tmp_path, evidence)
    queue = _queue(evidence[0])
    queue_body = _transport_body(
        runtime.queue.action(
            request=CourseReferenceQueueTransportRequest(
                scope=evidence[0].scope,
                selections=evidence[0].selections,
            )
        ).body_json
    )
    identity_request = _identity_transport_preview_request(queue, queue_body)
    identity_preview = runtime.identity_preview.action(request=identity_request)
    runtime.identity_put.action(
        request=_identity_transport_put_request(
            preview_request=identity_request,
            preview_body=_transport_body(identity_preview.body_json),
            rationale="Accept identity before selecting its source asset.",
            decided_at="2026-09-20T12:00:00Z",
            idempotency_key="asset-test-identity",
        )
    )
    queue_items = queue_body["items"]
    assert isinstance(queue_items, list)
    queue_item = queue_items[0]
    assert isinstance(queue_item, dict)
    candidate = queue_item["candidate"]
    assert isinstance(candidate, dict)
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    asset_bytes = b"%PDF-1.7\ncanonical fixture\n"
    (asset_root / "canonical.pdf").write_bytes(asset_bytes)
    raw_asset = SourceAssetRecord(
        candidate_id=_transport_string(candidate, "candidate_id"),
        proposed_citekey=_transport_string(candidate, "proposed_citekey"),
        identity_status=_transport_string(candidate, "identity_status"),
        citekey_status=_transport_string(candidate, "citekey_status"),
        sha256=hashlib.sha256(asset_bytes).hexdigest(),
        byte_size=len(asset_bytes),
        root_alias="runtime-assets",
        relative_path="canonical.pdf",
        rights_status="rights-not-assessed",
        asset_status="managed-private-integrity-validated-source",
    )
    catalog = ReferenceCatalog(
        configuration.catalog_path,
        storage_class=configuration.catalog_storage_class,
    )
    catalog.record_source_asset(raw_asset)
    observation_id = (
        ReferenceAssetAuthorityEvidenceActionizer()
        .action(request=ReferenceAssetAuthorityEvidenceRequest(asset=raw_asset))
        .evidence.asset_observation_id
    )
    source_id = "source:solid-state-fixture"
    document_id = (
        "reading-evidence-document:sha256:"
        "8a7358d8dafbf7da3d58f6b3233c9db0284f4ee0ec7d4891da1106bfd7942871"
    )
    verification_id = (
        "managed-artifact-verification-result:sha256:"
        "5c68aeb1065e4215cbfb07e12dcb0b54329a1010a58c04bb54d39d3469b60be0"
    )
    linkage_path = tmp_path / "asset-linkage.json"
    linkage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "asset_observation_id": observation_id,
                        "document_binding_ids": [
                            _cid("document-source-binding", "canonical")
                        ],
                        "ingestion_evidence_ids": [
                            _cid("ingestion-evidence", "canonical")
                        ],
                        "ingestion_artifact_links": [
                            {
                                "source_id": source_id,
                                "document_id": document_id,
                                "artifact_verification_result_id": (
                                    verification_id
                                ),
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    asset_configuration = replace(
        configuration,
        asset_roots=(
            CourseReferenceAuthorityAssetRoot(
                root_alias="runtime-assets",
                root_path=asset_root,
                storage_class=RootStorageClass.LOCAL,
            ),
        ),
        asset_linkage_path=linkage_path,
    )
    asset_runtime = (
        FilesystemCourseReferenceAuthorityRuntimeCreateActionizer().action(
            request=FilesystemCourseReferenceAuthorityRuntimeCreateRequest(
                configuration=asset_configuration
            )
        )
    )
    accepted_transport = asset_runtime.queue.action(
        request=CourseReferenceQueueTransportRequest(
            scope=evidence[0].scope,
            selections=evidence[0].selections,
        )
    )
    accepted_body = _transport_body(accepted_transport.body_json)
    accepted_items = accepted_body["items"]
    assert isinstance(accepted_items, list)
    accepted_item = accepted_items[0]
    assert isinstance(accepted_item, dict)
    assert isinstance(accepted_item["active_authority"], dict)
    accepted_assets = accepted_item["assets"]
    assert isinstance(accepted_assets, list)
    assert len(accepted_assets) == 1
    identity_projections = catalog.read_state_projections()
    assert len(identity_projections) == 1
    asset_preview_request = CanonicalAssetPreviewTransportRequest(
        scope=evidence[0].scope,
        selections=evidence[0].selections,
        selection_id=queue.items[0].selection.selection_id,
        expected_queue_id=_transport_string(accepted_body, "queue_id"),
        expected_item_revision_id=_transport_string(
            accepted_item,
            "item_revision_id",
        ),
        expected_identity_state_projection_id=(
            identity_projections[0].projection_id
        ),
        disposition=CanonicalAssetDecision.AUTHORIZE.name,
        competitors=(
            (
                observation_id,
                CanonicalAssetDecision.AUTHORIZE.name,
                "Select the exact freshly verified asset.",
            ),
        ),
        expected_current_decision_id=None,
    )
    asset_preview = asset_runtime.asset_preview.action(
        request=asset_preview_request
    )
    asset_preview_body = _transport_body(asset_preview.body_json)
    actor = _actor(ReviewAuthorityScope.CANONICAL_ASSET_CURATOR)
    put_request = CanonicalAssetPutTransportRequest(
        scope=asset_preview_request.scope,
        selections=asset_preview_request.selections,
        selection_id=asset_preview_request.selection_id,
        idempotency_key="asset-retry",
        expected_queue_id=_transport_string(
            asset_preview_body,
            "queue_id",
        ),
        expected_item_revision_id=_transport_string(
            asset_preview_body,
            "item_revision_id",
        ),
        expected_preview_id=_transport_string(
            asset_preview_body,
            "preview_id",
        ),
        expected_preview_result_id=_transport_string(
            asset_preview_body,
            "result_id",
        ),
        expected_identity_state_projection_id=(
            asset_preview_request.expected_identity_state_projection_id
        ),
        expected_asset_plan_id=_transport_string(
            asset_preview_body,
            "plan_id",
        ),
        expected_current_decision_id=None,
        disposition=asset_preview_request.disposition,
        competitors=asset_preview_request.competitors,
        rationale=(
            "Authorize the complete asset plan; rights remain unassessed."
        ),
        decided_at="2026-09-20T12:01:00Z",
        actor_id=actor.actor_id,
        actor_verification_record_id=actor.verification_record_id,
        actor_verification_method=actor.verification_method,
    )
    first = asset_runtime.asset_put.action(request=put_request)
    reopened = (
        FilesystemCourseReferenceAuthorityRuntimeCreateActionizer().action(
            request=FilesystemCourseReferenceAuthorityRuntimeCreateRequest(
                configuration=asset_configuration
            )
        )
    )
    assert reopened.asset_put.action(request=put_request) == first
    evidence_loader = FilesystemCourseReferenceAuthorityEvidenceLoadActionizer(
        course_id=asset_configuration.course_id,
        bibliography_sources=asset_configuration.bibliography_sources,
        record_discrepancies=asset_configuration.record_discrepancies,
        asset_roots=asset_configuration.asset_roots,
        asset_linkage_path=asset_configuration.asset_linkage_path,
        asset_linkage_storage_class=(
            asset_configuration.asset_linkage_storage_class
        ),
        asset_linkage_placeholder_probe=(
            asset_configuration.asset_linkage_placeholder_probe
        ),
    )
    refreshed_evidence = evidence_loader.action(
        request=CourseReferenceAuthorityEvidenceLoadRequest(
            scope=evidence[0].scope,
            catalog_candidates=catalog.read_candidates(),
            catalog_observations=catalog.read_observations(),
            catalog_assets=catalog.read_source_assets(),
        )
    )
    search = SearchReferenceAuthorityProjectionActionizer().action(
        request=SearchReferenceAuthorityProjectionRequest(
            review_projection=catalog.read_review_projection(),
            state_projections=catalog.read_state_projections(),
            asset_evidence=refreshed_evidence.assets,
        )
    )
    assert len(search.bindings) == 1
    link = search.bindings[0].ingestion_artifact_links[0]
    assert link.source_id == source_id
    assert link.document_id == document_id
    assert link.artifact_verification_result_id == verification_id


def test__golden_queue_and_preview_identities_match_9d351cd() -> None:
    """Keep the 9d351cd queue and preview identity graph byte-exact."""
    expected = json.loads(
        (
            Path(__file__).parents[5]
            / "fixtures/course-reference-authority"
            / "9d351cd-queue-identities.json"
        ).read_text(encoding="utf-8")
    )
    evidence = _evidence()
    queue = _queue(evidence[0])
    request = _identity_preview_request(queue)
    preview = ReferenceIdentityDecisionPreview(
        queue=queue,
        selection_id=request.selection_id,
        disposition=request.disposition,
        target_state_projection_id=request.target_state_projection_id,
        canonical_citekey=request.canonical_citekey,
        alias_citekeys=request.alias_citekeys,
        selected_record_match_ids=request.selected_record_match_ids,
        expected_current_decision_id=request.expected_current_decision_id,
    )
    from projectkoios.references.courses.authority.identity_preview import (
        ReferenceIdentityDecisionPreviewResult,
    )

    result = ReferenceIdentityDecisionPreviewResult(
        request_id=request.request_id,
        preview_id=preview.preview_id,
        selection_id=preview.selection_id,
        disposition=preview.disposition,
        target_state_projection_id=preview.target_state_projection_id,
        canonical_citekey=preview.canonical_citekey,
        alias_citekeys=preview.alias_citekeys,
        selected_record_match_ids=preview.selected_record_match_ids,
        expected_current_decision_id=preview.expected_current_decision_id,
        queue_id=queue.queue_id,
        item_revision_id=queue.items[0].item_revision_id,
    )
    actual = {
        "asset_observation_ids": [
            item.asset_observation_id
            for queue_item in queue.items
            for item in queue_item.assets
        ],
        "candidate_ids": [item.candidate_id for item in evidence[1]],
        "identity_preview_id": preview.preview_id,
        "identity_preview_request_id": request.request_id,
        "identity_preview_result_id": result.result_id,
        "item_revision_ids": [item.item_revision_id for item in queue.items],
        "queue_id": queue.queue_id,
        "queue_request_id": evidence[0].request_id,
        "render_result_id": evidence[0].render_result.result_id,
        "rendered_binding_ids": [
            item.binding_id for item in evidence[0].rendered_candidate_bindings
        ],
        "scope_id": evidence[0].scope.scope_id,
        "selection_ids": [item.selection.selection_id for item in queue.items],
    }
    assert actual == {
        key: value
        for key, value in expected.items()
        if key not in {"identity_put_request_id", "identity_put_scope_id"}
    }
    assert expected["identity_put_request_id"] == (
        "reference-authority-idempotency-request:sha256:"
        "d8d4799dbc61f00ad56c723cacbc7900b0930adedfbb25f191c3368651749dff"
    )
    assert expected["identity_put_scope_id"] == (
        "reference-authority-idempotency-scope:sha256:"
        "e5cc12f31fc52ed28060820c93e5625f5bdb3f2444320fbaf38e20a2e441316c"
    )
