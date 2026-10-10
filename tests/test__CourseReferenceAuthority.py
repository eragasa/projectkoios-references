from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyExportRequest,
    CandidateBibliographyRenderer,
    CandidateBibliographyRenderRequest,
    CandidateBibliographySourceDeclaration,
)
from projectkoios.references.catalog import (
    CatalogConflictError,
    ReferenceCatalog,
)
from projectkoios.references.course_reference_authority import (
    AppendCanonicalAssetDecisionRequest,
    AppendReferenceIdentityDecisionRequest,
    CourseDisplayCitekeyStatus,
    CourseReferenceAuthorityProjector,
    CourseReferenceAuthorityQueue,
    CourseReferenceAuthorityQueueRequest,
    CourseReferenceSelectionEvidence,
    ReferenceAssetAuthorityEvidence,
    ReferenceAuthorityDecisionAppender,
    ReferenceRecordDiscrepancy,
    ReferenceRecordMatchKind,
    RuntimeAssetAvailability,
    project_reviewed_course_references,
    project_search_reference_authority,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
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


def _evidence() -> tuple[
    CourseReferenceAuthorityQueueRequest,
    ReferenceCandidate,
]:
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
    entry = render.entries[0]
    fields = dict(entry.normalized_fields)
    candidate = ReferenceCandidate.create(
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
    display_status = CourseDisplayCitekeyStatus.PROPOSED_NONCANONICAL
    binding_payload = {
        "contract_version": "1.0",
        "display_citekey": entry.citekey,
        "display_citekey_status": display_status.value,
        "ordinal": 1,
        "reference_locator": entry.entry_id,
        "reference_owner": "projectkoios-references",
    }
    binding_digest = hashlib.sha256(
        json.dumps(
            binding_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    selection = CourseReferenceSelectionEvidence(
        scope_id=_cid("course-reference-resolution-scope", "scope"),
        selection_id=_cid("course-reference-selection", "selection"),
        locator_binding_id=(
            f"course-reference-locator-binding:sha256:{binding_digest}"
        ),
        course_id="dlsu-PHY627M-GS1",
        ordinal=1,
        display_citekey=entry.citekey,
        display_citekey_status=display_status,
        reference_locator=entry.entry_id,
    )
    request = CourseReferenceAuthorityQueueRequest(
        selections=(selection,),
        render_result=render,
        candidates=(candidate,),
        record_discrepancies=(
            ReferenceRecordDiscrepancy(
                citekey=entry.citekey,
                bibtex_entry=entry.rendered_entry.decode(),
            ),
            ReferenceRecordDiscrepancy(
                citekey=entry.citekey,
                bibtex_entry=imported.observations[0].verbatim_entry,
            ),
        ),
        assets=(),
        review_projection=replay_review_records((), ()),
        state_projections=(),
    )
    return request, candidate


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


def test__course_authority_queue__is_path_free_and_non_authoritative() -> None:
    request, candidate = _evidence()

    queue = _queue(request)
    item = queue.items[0]

    assert queue.control_class == "CONTROL"
    assert item.candidate == candidate
    assert item.selection.reference_locator == item.rendered_entry.entry_id
    assert item.observations[0].entry_sha256
    assert item.observations[0].entry_byte_size > 0
    assert not hasattr(item.observations[0], "source_path")
    assert not hasattr(item.observations[0], "verbatim_entry")
    assert not hasattr(item.rendered_entry, "rendered_entry")
    assert not hasattr(item.record_matches[0], "bibtex_entry")
    assert {match.kind for match in item.record_matches} == {
        ReferenceRecordMatchKind.EXACT_OBSERVED_KEY_AND_BYTES,
        ReferenceRecordMatchKind.EXACT_RENDERED_KEY_AND_BYTES,
    }
    assert item.allowed_identity_actions == (
        ReferenceIdentityDecision.ACCEPT_NEW,
        ReferenceIdentityDecision.REJECT,
        ReferenceIdentityDecision.DEFER,
    )
    assert ReferenceIdentityDecision.ACCEPT_EXISTING not in (
        item.allowed_identity_actions
    )
    assert ReferenceIdentityDecision.MERGE not in item.allowed_identity_actions
    assert item.allowed_asset_actions == ()
    assert "fixtures/render-specials.bib" not in repr(queue)
    assert request.render_result.request.source.sources[0].observations[
        0
    ].verbatim_entry not in repr(queue)
    assert request.render_result.entries[0].rendered_entry.decode() not in repr(
        queue
    )
    with pytest.raises(ValueError, match="not completely reviewed"):
        project_reviewed_course_references(queue=queue)


def test__accept_new__atomically_intakes_candidate_and_retries_exactly(
    tmp_path: Path,
) -> None:
    source_request, candidate = _evidence()
    queue = _queue(source_request)
    item = queue.items[0]
    catalog = _catalog(tmp_path / "references.sqlite3")
    observations = tuple(
        observation
        for source in source_request.render_result.request.source.sources
        for observation in source.observations
    )
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=(candidate,),
        observations=observations,
    )
    request = AppendReferenceIdentityDecisionRequest(
        queue=queue,
        selection_id=item.selection.selection_id,
        disposition=ReferenceIdentityDecision.ACCEPT_NEW,
        actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
        rationale="Accept the sanitized candidate as a new work.",
        decided_at="2026-09-20T12:00:00Z",
        expected_item_revision_id=item.item_revision_id,
        expected_current_decision_id=None,
    )

    result = appender.append_identity(request=request)
    retry = appender.append_identity(request=request)

    assert retry == result
    assert result.state_projection is not None
    assert catalog.read_candidates() == (candidate,)
    assert catalog.read_observations() == observations
    assert catalog.counts()["human_review_decisions"] == 1
    assert catalog.counts()["state_projections"] == 1
    projection = catalog.read_state_projections()[0]
    assert projection.field("identity_status").values[0].value_json == (
        '"accepted"'
    )
    assert projection.field("source_asset_id").values == ()


def test__defer__is_course_contextual_and_creates_no_authority(
    tmp_path: Path,
) -> None:
    source_request, candidate = _evidence()
    queue = _queue(source_request)
    item = queue.items[0]
    catalog = _catalog(tmp_path / "defer.sqlite3")
    observations = tuple(
        observation
        for source in source_request.render_result.request.source.sources
        for observation in source.observations
    )
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=(candidate,),
        observations=observations,
    )

    result = appender.append_identity(
        request=AppendReferenceIdentityDecisionRequest(
            queue=queue,
            selection_id=item.selection.selection_id,
            disposition=ReferenceIdentityDecision.DEFER,
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Defer only in this course context.",
            decided_at="2026-09-20T12:00:00Z",
            expected_item_revision_id=item.item_revision_id,
            expected_current_decision_id=None,
        )
    )

    assert result.decision.context_id == item.selection.course_id
    assert result.state_projection is None
    assert catalog.read_state_projections() == ()
    assert (
        project_search_reference_authority(
            review_projection=catalog.read_review_projection(),
            state_projections=(),
        ).bindings
        == ()
    )


def test__stale_identity_append__rolls_back_without_a_partial_decision(
    tmp_path: Path,
) -> None:
    source_request, candidate = _evidence()
    queue = _queue(source_request)
    item = queue.items[0]
    catalog = _catalog(tmp_path / "references.sqlite3")
    observations = tuple(
        observation
        for source in source_request.render_result.request.source.sources
        for observation in source.observations
    )
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=(candidate,),
        observations=observations,
    )
    actor = _actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR)
    first = AppendReferenceIdentityDecisionRequest(
        queue=queue,
        selection_id=item.selection.selection_id,
        disposition=ReferenceIdentityDecision.ACCEPT_NEW,
        actor=actor,
        rationale="First accepted decision.",
        decided_at="2026-09-20T12:00:00Z",
        expected_item_revision_id=item.item_revision_id,
        expected_current_decision_id=None,
    )
    stale = AppendReferenceIdentityDecisionRequest(
        queue=queue,
        selection_id=item.selection.selection_id,
        disposition=ReferenceIdentityDecision.ACCEPT_NEW,
        actor=actor,
        rationale="Competing stale decision.",
        decided_at="2026-09-20T12:00:00Z",
        expected_item_revision_id=item.item_revision_id,
        expected_current_decision_id=None,
    )

    accepted = appender.append_identity(request=first)
    with pytest.raises(CatalogConflictError, match="revision is stale"):
        appender.append_identity(request=stale)

    assert catalog.read_review_projection().human_decision_history == (
        accepted.decision,
    )
    assert catalog.counts()["human_review_decisions"] == 1
    assert catalog.counts()["state_projections"] == 1

    stale_candidate = ReferenceCandidate.create(
        proposed_citekey=candidate.proposed_citekey,
        entry_type=candidate.entry_type,
        title=f"{candidate.title} (conflicting proposal)",
        authors=candidate.authors,
        year=candidate.year,
        source_observation_ids=candidate.source_observation_ids,
        generator=candidate.generator,
    )
    stale_candidate_request = CourseReferenceAuthorityQueueRequest(
        selections=source_request.selections,
        render_result=source_request.render_result,
        candidates=(stale_candidate,),
        record_discrepancies=(),
        assets=(),
        review_projection=replay_review_records((), ()),
        state_projections=(),
    )
    stale_candidate_queue = _queue(stale_candidate_request)
    stale_candidate_item = stale_candidate_queue.items[0]
    stale_candidate_appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=(stale_candidate,),
        observations=observations,
    )
    with pytest.raises(CatalogConflictError, match="revision is stale"):
        stale_candidate_appender.append_identity(
            request=AppendReferenceIdentityDecisionRequest(
                queue=stale_candidate_queue,
                selection_id=stale_candidate_item.selection.selection_id,
                disposition=ReferenceIdentityDecision.ACCEPT_NEW,
                actor=actor,
                rationale="This entire append must roll back.",
                decided_at="2026-09-20T12:02:00Z",
                expected_item_revision_id=(
                    stale_candidate_item.item_revision_id
                ),
                expected_current_decision_id=None,
            )
        )
    assert catalog.read_candidates() == (candidate,)


def test__asset_authority_is_separate_and_search_requires_both_stages(
    tmp_path: Path,
) -> None:
    source_request, candidate = _evidence()
    initial_queue = _queue(source_request)
    item = initial_queue.items[0]
    catalog = _catalog(tmp_path / "references.sqlite3")
    observations = tuple(
        observation
        for source in source_request.render_result.request.source.sources
        for observation in source.observations
    )
    appender = ReferenceAuthorityDecisionAppender(
        repository=catalog,
        candidates=(candidate,),
        observations=observations,
    )
    identity = appender.append_identity(
        request=AppendReferenceIdentityDecisionRequest(
            queue=initial_queue,
            selection_id=item.selection.selection_id,
            disposition=ReferenceIdentityDecision.ACCEPT_NEW,
            actor=_actor(ReviewAuthorityScope.REFERENCE_IDENTITY_CURATOR),
            rationale="Accept work identity only.",
            decided_at="2026-09-20T12:00:00Z",
            expected_item_revision_id=item.item_revision_id,
            expected_current_decision_id=None,
        )
    )
    before_asset = project_search_reference_authority(
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
    )
    assert identity.state_projection is not None
    assert before_asset.bindings == ()

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
    catalog.record_source_asset(asset)
    asset_evidence = ReferenceAssetAuthorityEvidence.from_asset(
        asset,
        runtime_availability=RuntimeAssetAvailability.AVAILABLE,
        runtime_evidence_id=_cid("runtime-asset-evidence", "available"),
        document_binding_ids=(_cid("document-source-binding", "binding"),),
        ingestion_evidence_ids=(_cid("ingestion-evidence", "ingested"),),
    )
    current_request = CourseReferenceAuthorityQueueRequest(
        selections=source_request.selections,
        render_result=source_request.render_result,
        candidates=source_request.candidates,
        record_discrepancies=source_request.record_discrepancies,
        assets=(asset_evidence,),
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
    )
    current_queue = _queue(current_request)
    current_item = current_queue.items[0]
    assert "Accept work identity only." not in repr(current_queue)
    assert current_item.allowed_asset_actions == (
        CanonicalAssetDecision.AUTHORIZE,
        CanonicalAssetDecision.REJECT,
        CanonicalAssetDecision.DEFER,
    )
    asset_result = appender.append_asset(
        request=AppendCanonicalAssetDecisionRequest(
            queue=current_queue,
            selection_id=current_item.selection.selection_id,
            disposition=CanonicalAssetDecision.AUTHORIZE,
            actor=_actor(ReviewAuthorityScope.CANONICAL_ASSET_CURATOR),
            rationale=(
                "Authorize this exact source asset; rights remain unassessed."
            ),
            decided_at="2026-09-20T12:01:00Z",
            expected_item_revision_id=current_item.item_revision_id,
            expected_current_decision_id=None,
            selected_asset_observation_id=(asset_evidence.asset_observation_id),
        )
    )

    assert asset_result.state_projection is not None
    search = project_search_reference_authority(
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
    )
    assert len(search.bindings) == 1
    assert search.projection_id.startswith(
        "search-reference-authority-projection:sha256:"
    )
    assert search.result_id.startswith(
        "search-reference-authority-result:sha256:"
    )
    binding = search.bindings[0]
    assert binding.reference_identity_status == "accepted"
    assert binding.accepted_citekey == candidate.proposed_citekey
    assert binding.identity_decision_id == identity.decision.decision_id
    assert binding.canonical_asset_decision_id == (
        asset_result.decision.decision_id
    )
    assert identity.decision.decision_id in binding.authority_evidence_ids
    assert asset_result.decision.decision_id in binding.authority_evidence_ids
    assert asset_evidence.runtime_evidence_id in binding.authority_evidence_ids
    assert asset.relative_path not in repr(search)
    assert asset.root_alias not in repr(search)

    reviewed_request = CourseReferenceAuthorityQueueRequest(
        selections=source_request.selections,
        render_result=source_request.render_result,
        candidates=source_request.candidates,
        record_discrepancies=source_request.record_discrepancies,
        assets=(asset_evidence,),
        review_projection=catalog.read_review_projection(),
        state_projections=catalog.read_state_projections(),
    )
    reviewed = project_reviewed_course_references(
        queue=_queue(reviewed_request)
    )
    assert tuple(item.locator_binding_id for item in reviewed.bindings) == (
        source_request.selections[0].locator_binding_id,
    )
    assert reviewed.bindings[0].accepted_citekey == (candidate.proposed_citekey)
