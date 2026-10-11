from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
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
from projectkoios.references.course_reference_authority import (
    AppendCanonicalAssetDecisionRequest,
    AppendReferenceIdentityDecisionRequest,
    CanonicalAssetCompetitorDisposition,
    CanonicalAssetDecisionPreview,
    CanonicalAssetEvidencePlan,
    CourseDisplayCitekeyStatus,
    CourseReferenceAuthorityError,
    CourseReferenceAuthorityFailureReason,
    CourseReferenceAuthorityOwnerEvidence,
    CourseReferenceAuthorityProjector,
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueRequest,
    CourseReferenceAuthorityService,
    CourseReferenceAuthorityServiceError,
    CourseReferenceItemResolution,
    CourseReferenceResolutionScopeEvidence,
    CourseReferenceRole,
    CourseReferenceSelectionEvidence,
    CourseReferenceSelectionOrigin,
    IngestionArtifactAuthorityLink,
    ReferenceAssetAuthorityEvidence,
    ReferenceAuthorityDecisionAppender,
    ReferenceIdentityDecisionPreview,
    ReferenceRecordDiscrepancy,
    ReferenceRecordMatchKind,
    RenderedEntryCandidateBinding,
    RuntimeAssetAvailability,
    project_reviewed_course_references,
    project_search_reference_authority,
)
from projectkoios.references.course_reference_authority_runtime import (
    CourseReferenceAuthorityAssetRoot,
    CourseReferenceAuthorityBibliographySource,
    CourseReferenceAuthorityRuntimeConfiguration,
    FilesystemCourseReferenceAuthorityEvidenceProvider,
    open_course_reference_authority_service,
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
    Path(__file__).parent
    / "fixtures"
    / "candidate-bibliography"
    / "render-specials.bib"
)


def _cid(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"{kind}:sha256:{digest}"


def _locator_binding_id(
    *,
    ordinal: int,
    display_citekey: str,
    display_status: CourseDisplayCitekeyStatus,
    reference_locator: str,
) -> str:
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


@dataclass(frozen=True)
class _FixtureEvidence:
    request: CourseReferenceAuthorityQueueRequest
    candidates: tuple[ReferenceCandidate, ...]
    observations: tuple[SourceBibliographyObservation, ...]


def _candidate_for_entry(
    entry: CandidateBibliographyRenderedEntry,
) -> ReferenceCandidate:
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
) -> _FixtureEvidence:
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
    return _FixtureEvidence(
        request=request,
        candidates=candidates,
        observations=observations,
    )


def _evidence() -> _FixtureEvidence:
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
) -> _FixtureEvidence:
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
    return CourseReferenceAuthorityProjector().project(request=request)


def _catalog(path: Path) -> ReferenceCatalog:
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


def test__queue__retains_complete_scope_and_left_projects_unresolved(
    tmp_path: Path,
) -> None:
    complete = _fourteen_evidence(tmp_path)
    complete_queue = _queue(complete.request)
    assert len(complete_queue.items) == 14
    assert all(
        item.resolution is CourseReferenceItemResolution.READY
        for item in complete_queue.items
    )
    assert tuple(
        item.selection.selection_id for item in complete_queue.items
    ) == (complete.request.scope.ordered_selection_ids)

    incomplete = _fourteen_evidence(tmp_path, missing_last_binding=True)
    incomplete_queue = _queue(incomplete.request)
    assert len(incomplete_queue.items) == 14
    assert incomplete_queue.items[-1].resolution is (
        CourseReferenceItemResolution.CANDIDATE_UNAVAILABLE
    )
    assert incomplete_queue.items[-1].allowed_identity_actions == ()

    with pytest.raises(ValueError, match="complete Courses scope envelope"):
        CourseReferenceAuthorityQueueRequest(
            scope=complete.request.scope,
            selections=complete.request.selections[:-1],
            render_result=complete.request.render_result,
            candidates=complete.request.candidates,
            rendered_candidate_bindings=(
                complete.request.rendered_candidate_bindings
            ),
            record_discrepancies=(),
            assets=(),
            review_projection=complete.request.review_projection,
            state_projections=(),
        )


def test__queue__is_path_byte_free_and_revalidates_mutated_binding() -> None:
    evidence = _evidence()
    queue = _queue(evidence.request)
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
        project_reviewed_course_references(queue=queue)

    object.__setattr__(
        evidence.request.selections[0],
        "locator_binding_id",
        _cid("course-reference-locator-binding", "mutated"),
    )
    with pytest.raises(ValueError, match="locator binding"):
        _queue(evidence.request)

    binding_evidence = _evidence()
    object.__setattr__(
        binding_evidence.request.rendered_candidate_bindings[0],
        "candidate_id",
        _cid("reference-candidate", "mutated"),
    )
    with pytest.raises(ValueError, match="request revision is stale"):
        _queue(binding_evidence.request)


def test__candidate_resolution__uses_explicit_binding_not_citekey_join() -> (
    None
):
    evidence = _evidence()
    candidate = evidence.candidates[0]
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
        reference_locator=evidence.request.render_result.entries[0].entry_id,
        rendered_entry_id=evidence.request.render_result.entries[0].entry_id,
        candidate_id=changed.candidate_id,
        source_observation_ids=changed.source_observation_ids,
    )
    request = CourseReferenceAuthorityQueueRequest(
        scope=evidence.request.scope,
        selections=evidence.request.selections,
        render_result=evidence.request.render_result,
        candidates=(changed,),
        rendered_candidate_bindings=(binding,),
        record_discrepancies=(),
        assets=(),
        review_projection=evidence.request.review_projection,
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
        reference_locator=evidence.request.render_result.entries[0].entry_id,
        rendered_entry_id=evidence.request.render_result.entries[0].entry_id,
        candidate_id=same_key_other.candidate_id,
        source_observation_ids=same_key_other.source_observation_ids,
    )
    same_key_request = CourseReferenceAuthorityQueueRequest(
        scope=evidence.request.scope,
        selections=evidence.request.selections,
        render_result=evidence.request.render_result,
        candidates=(candidate, same_key_other),
        rendered_candidate_bindings=(same_key_binding,),
        record_discrepancies=(),
        assets=(),
        review_projection=evidence.request.review_projection,
        state_projections=(),
    )
    same_key_item = _queue(same_key_request).items[0]
    assert same_key_item.resolution is CourseReferenceItemResolution.READY
    assert same_key_item.candidate == same_key_other


def test__identity_preview_append_is_atomic_retryable_and_defer_is_contextual(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    queue = _queue(evidence.request)
    catalog = _catalog(tmp_path / "references.sqlite3")
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=evidence.candidates,
        observations=evidence.observations,
    )
    preview = _identity_preview(queue)
    request = AppendReferenceIdentityDecisionRequest(
        preview=preview,
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="Accept the exact explicit identity preview.",
        decided_at="2026-09-20T12:00:00Z",
    )
    result = appender.append_identity(request=request)
    assert appender.append_identity(request=request) == result
    assert catalog.read_candidates() == evidence.candidates
    assert catalog.counts()["human_review_decisions"] == 1
    assert catalog.counts()["state_projections"] == 1

    defer_catalog = _catalog(tmp_path / "defer.sqlite3")
    defer_queue = _queue(evidence.request)
    defer_result = ReferenceAuthorityDecisionAppender(
        repository=defer_catalog,
        candidates=evidence.candidates,
        observations=evidence.observations,
    ).append_identity(
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
    assert defer_result.decision.context_id == evidence.request.scope.course_id
    assert defer_result.state_projection is None


def test__stale_preview_rolls_back_candidate_and_decision(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    queue = _queue(evidence.request)
    catalog = _catalog(tmp_path / "references.sqlite3")
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=evidence.candidates,
        observations=evidence.observations,
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
    accepted = appender.append_identity(request=first)
    with pytest.raises(CatalogConflictError, match="revision is stale"):
        appender.append_identity(request=stale)
    assert catalog.read_review_projection().human_decision_history == (
        accepted.decision,
    )


def _asset_evidence(
    asset: SourceAssetRecord,
    *,
    runtime_token: str,
) -> ReferenceAssetAuthorityEvidence:
    base = ReferenceAssetAuthorityEvidence.from_asset(asset)
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
    return ReferenceAssetAuthorityEvidence.from_asset(
        asset,
        runtime_availability=RuntimeAssetAvailability.AVAILABLE,
        runtime_evidence_id=_cid("runtime-asset-evidence", runtime_token),
        document_binding_ids=(_cid("document-source-binding", "binding"),),
        ingestion_evidence_ids=(_cid("ingestion-evidence", "ingested"),),
        ingestion_artifact_links=(link,),
    )


def test__ingestion_link__accepts_exact_opaque_source_identity() -> None:
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


def test__asset_plan_and_search_require_typed_ingestion_linkage(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    catalog = _catalog(tmp_path / "references.sqlite3")
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=evidence.candidates,
        observations=evidence.observations,
    )
    identity = appender.append_identity(
        request=AppendReferenceIdentityDecisionRequest(
            preview=_identity_preview(_queue(evidence.request)),
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Accept identity only.",
            decided_at="2026-09-20T12:00:00Z",
        )
    )
    candidate = evidence.candidates[0]
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
        scope=evidence.request.scope,
        selections=evidence.request.selections,
        render_result=evidence.request.render_result,
        candidates=evidence.candidates,
        rendered_candidate_bindings=evidence.request.rendered_candidate_bindings,
        record_discrepancies=evidence.request.record_discrepancies,
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
    asset_result = appender.append_asset(
        request=AppendCanonicalAssetDecisionRequest(
            preview=preview,
            actor=_actor(ReviewAuthorityScope.CANONICAL_ASSET_CURATOR),
            rationale="Authorize linkage; rights remain unassessed.",
            decided_at="2026-09-20T12:01:00Z",
        )
    )
    unlinked_asset_evidence = ReferenceAssetAuthorityEvidence.from_asset(
        asset,
        runtime_availability=RuntimeAssetAvailability.AVAILABLE,
        runtime_evidence_id=_cid("runtime-asset-evidence", "unlinked"),
    )
    without_link = project_search_reference_authority(
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
        asset_evidence=(unlinked_asset_evidence,),
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
    mismatched_evidence = ReferenceAssetAuthorityEvidence.from_asset(
        asset,
        runtime_availability=RuntimeAssetAvailability.AVAILABLE,
        runtime_evidence_id=asset_evidence.runtime_evidence_id,
        document_binding_ids=asset_evidence.document_binding_ids,
        ingestion_evidence_ids=asset_evidence.ingestion_evidence_ids,
        ingestion_artifact_links=(mismatched_link,),
    )
    assert (
        project_search_reference_authority(
            review_projection=catalog.read_review_projection(),
            state_projections=catalog.read_state_projections(),
            asset_evidence=(mismatched_evidence,),
        ).bindings
        == ()
    )
    stale_runtime_evidence = ReferenceAssetAuthorityEvidence.from_asset(
        asset,
        runtime_availability=RuntimeAssetAvailability.AVAILABLE,
        runtime_evidence_id=_cid("runtime-asset-evidence", "stale"),
        document_binding_ids=asset_evidence.document_binding_ids,
        ingestion_evidence_ids=asset_evidence.ingestion_evidence_ids,
        ingestion_artifact_links=asset_evidence.ingestion_artifact_links,
    )
    assert (
        project_search_reference_authority(
            review_projection=catalog.read_review_projection(),
            state_projections=catalog.read_state_projections(),
            asset_evidence=(stale_runtime_evidence, competitor_evidence),
        ).bindings
        == ()
    )
    search = project_search_reference_authority(
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
        asset_evidence=(asset_evidence, competitor_evidence),
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
    evidence = _evidence()
    with pytest.raises(ValueError, match="differ from render observations"):
        CourseReferenceAuthorityOwnerEvidence(
            render_result=evidence.request.render_result,
            candidates=evidence.candidates,
            observations=(),
            rendered_candidate_bindings=(
                evidence.request.rendered_candidate_bindings
            ),
            record_discrepancies=(),
            assets=(),
        )


def test__filesystem_provider_factory__owns_private_parsing_and_catalog_reads(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    catalog_path = tmp_path / "references.sqlite3"
    _catalog(catalog_path)
    digest = hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    configuration = CourseReferenceAuthorityRuntimeConfiguration(
        course_id=evidence.request.scope.course_id,
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
    service = open_course_reference_authority_service(
        configuration=configuration
    )
    queue = service.queue(
        scope=evidence.request.scope,
        selections=evidence.request.selections,
    )
    assert tuple(item.selection.selection_id for item in queue.items) == (
        evidence.request.scope.ordered_selection_ids
    )
    assert all(
        item.resolution is CourseReferenceItemResolution.READY
        for item in queue.items
    )


def test__filesystem_provider__reobserves_asset_and_linkage_evidence(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    asset_path = asset_root / "asset.pdf"
    initial_bytes = b"%PDF-1.7\nfixture\n"
    asset_path.write_bytes(initial_bytes)
    candidate = evidence.candidates[0]
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
    asset_observation_id = ReferenceAssetAuthorityEvidence.from_asset(
        raw_asset
    ).asset_observation_id
    linkage_path = tmp_path / "linkage.json"

    def write_linkage(source_id: str) -> None:
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
    provider = FilesystemCourseReferenceAuthorityEvidenceProvider(
        course_id=evidence.request.scope.course_id,
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
        owner = provider.load_course_reference_authority_evidence(
            scope=evidence.request.scope,
            catalog_candidates=(),
            catalog_observations=(),
            catalog_assets=(raw_asset,),
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


class _Provider:
    def __init__(self, evidence: _FixtureEvidence) -> None:
        self.evidence = evidence
        self.assets: tuple[ReferenceAssetAuthorityEvidence, ...] = ()

    def load_course_reference_authority_evidence(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        catalog_candidates: tuple[ReferenceCandidate, ...],
        catalog_observations: tuple[SourceBibliographyObservation, ...],
        catalog_assets: tuple[SourceAssetRecord, ...],
    ) -> CourseReferenceAuthorityOwnerEvidence:
        candidates = {
            item.candidate_id: item
            for item in (*catalog_candidates, *self.evidence.candidates)
        }
        observations = {
            item.observation_id: item
            for item in (*catalog_observations, *self.evidence.observations)
        }
        return CourseReferenceAuthorityOwnerEvidence(
            render_result=self.evidence.request.render_result,
            candidates=tuple(
                sorted(candidates.values(), key=lambda item: item.candidate_id)
            ),
            observations=tuple(
                sorted(
                    observations.values(), key=lambda item: item.observation_id
                )
            ),
            rendered_candidate_bindings=(
                self.evidence.request.rendered_candidate_bindings
            ),
            record_discrepancies=self.evidence.request.record_discrepancies,
            assets=self.assets,
        )


def _service_identity_context(
    tmp_path: Path,
) -> tuple[
    CourseReferenceAuthorityService,
    _FixtureEvidence,
    ReferenceIdentityDecisionPreview,
]:
    evidence = _evidence()
    service = CourseReferenceAuthorityService(
        catalog=_catalog(tmp_path / "service.sqlite3"),
        provider=_Provider(evidence),
    )
    preview = service.preview_identity(
        scope=evidence.request.scope,
        selections=evidence.request.selections,
        selection_id=evidence.request.selections[0].selection_id,
        disposition=ReferenceIdentityDecision.ACCEPT_NEW,
        target_state_projection_id=None,
        canonical_citekey=evidence.candidates[0].proposed_citekey,
        alias_citekeys=(),
        selected_record_match_ids=(),
        expected_current_decision_id=None,
    )
    return service, evidence, preview


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (
            CatalogConflictError("synthetic conflict"),
            CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION,
        ),
        (
            CourseReferenceAuthorityError("synthetic malformed owner"),
            CourseReferenceAuthorityFailureReason.OWNER_MALFORMED,
        ),
        (
            OSError("synthetic unavailable owner"),
            CourseReferenceAuthorityFailureReason.OWNER_UNAVAILABLE,
        ),
    ),
)
def test__service_append__maps_owner_failures_without_message_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    reason: CourseReferenceAuthorityFailureReason,
) -> None:
    service, _, preview = _service_identity_context(tmp_path)

    def fail_append(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(
        ReferenceAuthorityDecisionAppender,
        "append_identity",
        fail_append,
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as captured:
        service.append_identity(
            preview=preview,
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Exercise the typed service boundary.",
            decided_at="2026-09-20T12:00:00Z",
        )
    assert captured.value.reason is reason


def test__service_exact_retry_failure_does_not_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, preview = _service_identity_context(tmp_path)
    actor = _actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR)
    service.append_identity(
        preview=preview,
        actor=actor,
        rationale="Commit before exact retry.",
        decided_at="2026-09-20T12:00:00Z",
    )

    def fail_retry(*args: object, **kwargs: object) -> None:
        raise CatalogConflictError("synthetic retry conflict")

    monkeypatch.setattr(
        ReferenceAuthorityDecisionAppender,
        "append_identity",
        fail_retry,
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as captured:
        service.append_identity(
            preview=preview,
            actor=actor,
            rationale="Commit before exact retry.",
            decided_at="2026-09-20T12:00:00Z",
        )
    assert captured.value.reason is (
        CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION
    )


def test__service_receipt_validation_failure_does_not_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, preview = _service_identity_context(tmp_path)

    def fail_receipt(*args: object, **kwargs: object) -> None:
        raise CourseReferenceAuthorityError("synthetic receipt mismatch")

    monkeypatch.setattr(
        CourseReferenceAuthorityService,
        "_receipt",
        fail_receipt,
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as captured:
        service.append_identity(
            preview=preview,
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Exercise receipt validation translation.",
            decided_at="2026-09-20T12:00:00Z",
        )
    assert captured.value.reason is (
        CourseReferenceAuthorityFailureReason.OWNER_MALFORMED
    )


def test__service_rereads_receipt_and_rejects_stale_runtime_plan(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    catalog = _catalog(tmp_path / "service.sqlite3")
    provider = _Provider(evidence)
    service = CourseReferenceAuthorityService(
        catalog=catalog,
        provider=provider,
    )
    selections = evidence.request.selections
    with pytest.raises(CourseReferenceAuthorityServiceError) as missing:
        service.preview_identity(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=_cid("course-reference-selection", "missing"),
            disposition=ReferenceIdentityDecision.REJECT,
            target_state_projection_id=None,
            canonical_citekey=None,
            alias_citekeys=(),
            selected_record_match_ids=(),
            expected_current_decision_id=None,
        )
    assert missing.value.reason is (
        CourseReferenceAuthorityFailureReason.ITEM_NOT_FOUND
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as stale_head:
        service.preview_identity(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=selections[0].selection_id,
            disposition=ReferenceIdentityDecision.ACCEPT_NEW,
            target_state_projection_id=None,
            canonical_citekey=evidence.candidates[0].proposed_citekey,
            alias_citekeys=(),
            selected_record_match_ids=(),
            expected_current_decision_id=_cid(
                "human-review-decision",
                "stale",
            ),
        )
    assert stale_head.value.reason is (
        CourseReferenceAuthorityFailureReason.REVISION_STALE
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as stale_target:
        service.preview_identity(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=selections[0].selection_id,
            disposition=ReferenceIdentityDecision.REJECT,
            target_state_projection_id=_cid(
                "reference-state-projection",
                "missing",
            ),
            canonical_citekey=None,
            alias_citekeys=(),
            selected_record_match_ids=(),
            expected_current_decision_id=None,
        )
    assert stale_target.value.reason is (
        CourseReferenceAuthorityFailureReason.TARGET_STALE
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as invalid_match:
        service.preview_identity(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=selections[0].selection_id,
            disposition=ReferenceIdentityDecision.ACCEPT_NEW,
            target_state_projection_id=None,
            canonical_citekey=evidence.candidates[0].proposed_citekey,
            alias_citekeys=(),
            selected_record_match_ids=(_cid("reference-record", "missing"),),
            expected_current_decision_id=None,
        )
    assert invalid_match.value.reason is (
        CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION
    )
    identity_preview = service.preview_identity(
        scope=evidence.request.scope,
        selections=selections,
        selection_id=selections[0].selection_id,
        disposition=ReferenceIdentityDecision.ACCEPT_NEW,
        target_state_projection_id=None,
        canonical_citekey=evidence.candidates[0].proposed_citekey,
        alias_citekeys=(),
        selected_record_match_ids=(),
        expected_current_decision_id=None,
    )
    receipt = service.append_identity(
        preview=identity_preview,
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="Commit and reread identity.",
        decided_at="2026-09-20T12:00:00Z",
    )
    assert (
        receipt.current_decision_id
        == receipt.decision_result.decision.decision_id
    )
    assert receipt.preview_id == identity_preview.preview_id
    assert receipt.refreshed_queue.queue_id == receipt.refreshed_queue_id
    assert (
        receipt.refreshed_item.selection.selection_id
        == selections[0].selection_id
    )
    retry_receipt = service.append_identity(
        preview=identity_preview,
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="Commit and reread identity.",
        decided_at="2026-09-20T12:00:00Z",
    )
    assert retry_receipt.decision_result == receipt.decision_result
    active_queue = service.queue(
        scope=evidence.request.scope,
        selections=selections,
    )
    assert active_queue.items[0].active_authority is not None
    with pytest.raises(
        CourseReferenceAuthorityServiceError
    ) as invalid_target_use:
        service.preview_identity(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=selections[0].selection_id,
            disposition=ReferenceIdentityDecision.REJECT,
            target_state_projection_id=(
                active_queue.items[0].active_authority.state_projection_id
            ),
            canonical_citekey=None,
            alias_citekeys=("invalidAlias",),
            selected_record_match_ids=(),
            expected_current_decision_id=receipt.current_decision_id,
        )
    assert invalid_target_use.value.reason is (
        CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION
    )

    candidate = evidence.candidates[0]
    raw_asset = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256="b" * 64,
        byte_size=84,
        root_alias="private-library",
        relative_path="service.pdf",
        rights_status="rights-not-assessed",
        asset_status="observed-source-copy",
    )
    catalog.record_source_asset(raw_asset)
    provider.assets = (_asset_evidence(raw_asset, runtime_token="first"),)
    with pytest.raises(
        CourseReferenceAuthorityServiceError
    ) as stale_asset_head:
        service.preview_asset(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=selections[0].selection_id,
            disposition=CanonicalAssetDecision.AUTHORIZE,
            competitor_dispositions=(
                CanonicalAssetCompetitorDisposition(
                    asset_observation_id=(
                        provider.assets[0].asset_observation_id
                    ),
                    disposition=CanonicalAssetDecision.AUTHORIZE,
                    rationale="Select the only competitor.",
                ),
            ),
            expected_current_decision_id=_cid(
                "human-review-decision",
                "stale-asset",
            ),
        )
    assert stale_asset_head.value.reason is (
        CourseReferenceAuthorityFailureReason.REVISION_STALE
    )
    with pytest.raises(CourseReferenceAuthorityServiceError) as invalid_asset:
        service.preview_asset(
            scope=evidence.request.scope,
            selections=selections,
            selection_id=selections[0].selection_id,
            disposition=CanonicalAssetDecision.AUTHORIZE,
            competitor_dispositions=(),
            expected_current_decision_id=None,
        )
    assert invalid_asset.value.reason is (
        CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION
    )
    asset_preview = service.preview_asset(
        scope=evidence.request.scope,
        selections=selections,
        selection_id=selections[0].selection_id,
        disposition=CanonicalAssetDecision.AUTHORIZE,
        competitor_dispositions=(
            CanonicalAssetCompetitorDisposition(
                asset_observation_id=provider.assets[0].asset_observation_id,
                disposition=CanonicalAssetDecision.AUTHORIZE,
                rationale="Select the only competitor.",
            ),
        ),
        expected_current_decision_id=None,
    )
    provider.assets = (_asset_evidence(raw_asset, runtime_token="changed"),)
    with pytest.raises(CourseReferenceAuthorityServiceError) as captured:
        service.append_asset(
            preview=asset_preview,
            actor=_actor(ReviewAuthorityScope.CANONICAL_ASSET_CURATOR),
            rationale="This stale plan must not append.",
            decided_at="2026-09-20T12:01:00Z",
        )
    assert captured.value.reason is (
        CourseReferenceAuthorityFailureReason.EVIDENCE_STALE
    )
    assert catalog.counts()["human_review_decisions"] == 1


def test__optional_private_exact_fourteen_smoke() -> None:
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
    provider = FilesystemCourseReferenceAuthorityEvidenceProvider(
        course_id=scope.course_id,
        bibliography_sources=sources,
    )
    evidence = provider.load_course_reference_authority_evidence(
        scope=scope,
        catalog_candidates=(),
        catalog_observations=(),
        catalog_assets=(),
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
