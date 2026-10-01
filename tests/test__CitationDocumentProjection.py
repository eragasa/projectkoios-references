from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, fields, replace

import pytest
from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.citation_document import (
    CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS,
    CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES,
    CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
    CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY,
    CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY,
    CITATION_DOCUMENT_MAX_OCCURRENCES,
    CITATION_DOCUMENT_MAX_PDF_BYTES,
    CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS,
    CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES,
    CITATION_DOCUMENT_MAX_TARGET_RECORDS,
    CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD,
    CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES,
    CITATION_DOCUMENT_MAX_TEXT_BYTES,
    CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
    CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
    CitationBibliographyMembershipStatus,
    CitationBibliographyObservationBinding,
    CitationContentIdentity,
    CitationDocumentAvailabilityStatus,
    CitationDocumentProjection,
    CitationDocumentProjectionItem,
    CitationDocumentProjectionRequest,
    CitationDocumentProjectionResult,
    CitationDocumentProjector,
    CitationKeyResolutionStatus,
    CitationSourceDocumentDescriptor,
    CitationSourceDocumentLink,
    CitationSourceDocumentLinker,
    CitationSourceDocumentLinkRequest,
    CitationSourceDocumentLinkResult,
    CitationSourceDocumentObservation,
    CitationSourceLocator,
    CitationTargetBibliographyEntry,
    CitationTargetGroup,
    CitationTargetOccurrence,
    CitationTargetSnapshot,
    CitationTargetSourceGap,
)
from projectkoios.references.citation_document._contract import stable_id
from projectkoios.references.citation_identity import (
    CitationIdentityProjectionStatus,
)
from projectkoios.references.identity import (
    ActorAuthorityScope,
    ActorKind,
    ActorProvenance,
    IdentityDecision,
    IdentityProjection,
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
    replay_identity_decisions,
)


def _target_id(prefix: str, label: str) -> str:
    return f"{prefix}:{hashlib.sha256(label.encode()).hexdigest()}"


def _canonical_id(prefix: str, payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{prefix}:sha256:{hashlib.sha256(canonical).hexdigest()}"


def _content(content: bytes) -> CitationContentIdentity:
    return CitationContentIdentity(
        algorithm="sha256",
        digest=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
    )


def _locator(
    *,
    path: str,
    content: bytes,
    include_index: int,
    start: int,
    end: int,
    line: int,
    column: int,
) -> CitationSourceLocator:
    return CitationSourceLocator(
        source_path=path,
        source_content_identity=_content(content),
        include_index=include_index,
        byte_start=start,
        byte_end=end,
        line=line,
        column=column,
    )


def _actor() -> ActorProvenance:
    return ActorProvenance(
        actor_id="person:citation-document-reviewer",
        actor_kind=ActorKind.PERSON,
        authority_scope=ActorAuthorityScope.REFERENCE_IDENTITY_CURATOR,
        verification_record_id="actor-verification:sha256:" + "a" * 64,
        verification_method="synthetic-authentication-record",
    )


def _candidate(
    *,
    key: str,
    title: str,
    observation: SourceBibliographyObservation,
) -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey=key,
        entry_type="article",
        title=title,
        authors=("A. Author",),
        year="2026",
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("citation-document-fixture", title),
    )


def _fixture() -> tuple[
    CitationTargetSnapshot,
    tuple[CitationBibliographyObservationBinding, ...],
    IdentityProjection,
]:
    entry_keys = ("acceptedKey", "ambiguousKey", "candidateOnly", "unresolved")
    verbatim = tuple(f"@article{{{key}}}\n" for key in entry_keys)
    bibliography_bytes = "".join(verbatim).encode()
    bibliography_identity = _content(bibliography_bytes)
    observations: list[SourceBibliographyObservation] = []
    entries: list[CitationTargetBibliographyEntry] = []
    cursor = 0
    for index, (key, text) in enumerate(zip(entry_keys, verbatim, strict=True)):
        encoded = text.encode()
        observation = SourceBibliographyObservation.create(
            source_id="citation-document-fixture",
            asserted_source_revision="synthetic-target-revision",
            source_path="references.bib",
            bibliography_bytes=bibliography_bytes,
            entry_index=index,
            observed_citekey=key,
            verbatim_entry=text,
            parser=ProducerIdentity("synthetic-bib-parser", "1"),
        )
        observations.append(observation)
        entries.append(
            CitationTargetBibliographyEntry(
                entry_id=_target_id("citation-entry", key),
                entry_index=index,
                key=key,
                entry_type="article",
                locator=CitationSourceLocator(
                    source_path="references.bib",
                    source_content_identity=bibliography_identity,
                    include_index=0,
                    byte_start=cursor,
                    byte_end=cursor + len(encoded),
                    line=index + 1,
                    column=1,
                ),
                entry_content_identity=_content(encoded),
                source_bibliography_observation_id=None,
            )
        )
        cursor += len(encoded)

    source = (
        b"accepted accepted alias ambiguous candidate unresolved source-gap"
    )
    occurrence_values = (
        ("acceptedKey", 0, "direct", None),
        ("acceptedKey", 0, "citation_todo_expansion", 0),
        ("aliasOld", None, "eqincite_expansion", None),
        ("ambiguousKey", 1, "direct", None),
        ("candidateOnly", 2, "direct", None),
        ("unresolved", 3, "direct", None),
    )
    occurrences = tuple(
        CitationTargetOccurrence(
            occurrence_id=_target_id(
                "citation-occurrence",
                f"{key}-{index}",
            ),
            occurrence_index=index,
            call_index=index,
            key_index=0,
            key=key,
            origin=origin,
            locator=_locator(
                path="main.tex",
                content=source,
                include_index=0,
                start=index,
                end=index + 1,
                line=index + 1,
                column=1,
            ),
            bibliography_entry_index=entry_index,
            todo_marker_index=todo_marker_index,
        )
        for index, (
            key,
            entry_index,
            origin,
            todo_marker_index,
        ) in enumerate(occurrence_values)
    )
    grouped: dict[str, list[int]] = {}
    for occurrence in occurrences:
        grouped.setdefault(occurrence.key, []).append(
            occurrence.occurrence_index
        )
    entry_index_by_key = {entry.key: entry.entry_index for entry in entries}
    groups = tuple(
        CitationTargetGroup(
            group_id=_target_id("citation-group", key),
            group_index=index,
            key=key,
            occurrence_indexes=tuple(grouped[key]),
            direct_occurrence_count=sum(
                occurrences[item].origin != "citation_todo_expansion"
                for item in grouped[key]
            ),
            generated_occurrence_count=sum(
                occurrences[item].origin == "citation_todo_expansion"
                for item in grouped[key]
            ),
            bibliography_entry_index=entry_index_by_key.get(key),
        )
        for index, key in enumerate(sorted(grouped))
    )
    gap = CitationTargetSourceGap(
        source_gap_id=_target_id("citation-gap", "gap-1"),
        source_gap_index=0,
        locator=_locator(
            path="main.tex",
            content=source,
            include_index=0,
            start=len(source) - 3,
            end=len(source) - 2,
            line=20,
            column=1,
        ),
        reason="placeholder_identifier",
        placeholder_identifier="future-reference-placeholder",
    )
    snapshot = CitationTargetSnapshot(
        snapshot_id=_target_id("citation-snapshot", "complete-target"),
        bibliography_source_path="references.bib",
        bibliography_content_identity=bibliography_identity,
        occurrences=occurrences,
        groups=groups,
        bibliography_entries=tuple(entries),
        source_gaps=(gap,),
        missing_keys=("aliasOld",),
        duplicate_keys=(),
        uncited_keys=(),
    )
    bindings = tuple(
        CitationBibliographyObservationBinding(
            entry=entry,
            observation=observation,
        )
        for entry, observation in zip(entries, observations, strict=True)
    )

    accepted = _candidate(
        key="acceptedKey",
        title="Accepted",
        observation=observations[0],
    )
    ambiguous_one = _candidate(
        key="ambiguousKey",
        title="Ambiguous One",
        observation=observations[1],
    )
    ambiguous_two = _candidate(
        key="ambiguousKey",
        title="Ambiguous Two",
        observation=observations[1],
    )
    candidate_only = _candidate(
        key="candidateOnly",
        title="Candidate Only",
        observation=observations[2],
    )
    candidates = tuple(
        sorted(
            (
                accepted,
                ambiguous_one,
                ambiguous_two,
                candidate_only,
            ),
            key=lambda item: item.candidate_id,
        )
    )
    actor = _actor()
    promotion = IdentityDecision.promotion(
        candidate_ids=(accepted.candidate_id,),
        canonical_citekey="acceptedKey",
        actor=actor,
        evidence_ids=tuple(
            sorted(
                (
                    accepted.candidate_id,
                    observations[0].observation_id,
                    actor.verification_record_id,
                )
            )
        ),
        rationale="Accept the synthetic reference identity.",
    )
    promoted = replay_identity_decisions(candidates, (promotion,))
    alias = IdentityDecision.alias(
        target_reference_id=promoted.active_reference_ids[0],
        alias_citekey="aliasOld",
        actor=actor,
        evidence_ids=tuple(
            sorted(
                (
                    promoted.active_reference_ids[0],
                    actor.verification_record_id,
                )
            )
        ),
        rationale="Retain an active synthetic alias.",
    )
    projection = replay_identity_decisions(candidates, (promotion, alias))
    return snapshot, bindings, projection


def _projection_request(
    *,
    observations: tuple[CitationSourceDocumentObservation, ...] = (),
    links: tuple[CitationSourceDocumentLinkResult, ...] = (),
) -> CitationDocumentProjectionRequest:
    snapshot, bindings, identity_projection = _fixture()
    return CitationDocumentProjectionRequest(
        target_snapshot=snapshot,
        bibliography_bindings=bindings,
        identity_projection=identity_projection,
        document_observations=observations,
        source_document_link_results=links,
    )


def _descriptor(label: str) -> CitationSourceDocumentDescriptor:
    content = f"%PDF-{label}".encode()
    return CitationSourceDocumentDescriptor(
        source_document_id=f"application-source:{label}",
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
    )


def _document_observation(
    *,
    key: str,
    coverage: str,
    documents: tuple[CitationSourceDocumentDescriptor, ...] = (),
    inaccessible: tuple[str, ...] = (),
    evidence: str = "application-receipt:synthetic",
) -> CitationSourceDocumentObservation:
    snapshot, _, _ = _fixture()
    return CitationSourceDocumentObservation(
        target_snapshot_id=snapshot.snapshot_id,
        literal_citekey=key,
        coverage_status=coverage,
        source_documents=tuple(
            sorted(documents, key=lambda item: item.descriptor_id)
        ),
        inaccessible_evidence_ids=tuple(sorted(inaccessible)),
        evidence_id=evidence,
    )


def test__projector__bridges_literal_keys_without_first_win() -> None:
    request = _projection_request()

    result = CitationDocumentProjector().project(request=request)
    by_key = {item.literal_citekey: item for item in result.projection.items}

    accepted = by_key["acceptedKey"]
    assert accepted.bibliography_membership_status is (
        CitationBibliographyMembershipStatus.DEFINED
    )
    assert (
        accepted.key_resolution_status is CitationKeyResolutionStatus.RESOLVED
    )
    assert accepted.identity_items[0].status is (
        CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL
    )
    assert accepted.identity_items[0].canonical_citekey == "acceptedKey"
    assert len(accepted.occurrence_ids) == 2

    alias = by_key["aliasOld"]
    assert alias.bibliography_membership_status is (
        CitationBibliographyMembershipStatus.UNDEFINED
    )
    assert alias.key_resolution_status is CitationKeyResolutionStatus.RESOLVED
    assert alias.identity_items[0].status is (
        CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL
    )
    assert alias.identity_items[0].canonical_citekey == "acceptedKey"

    candidate = by_key["candidateOnly"]
    assert candidate.key_resolution_status is (
        CitationKeyResolutionStatus.RESOLVED
    )
    assert candidate.identity_items[0].status is (
        CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
    )

    ambiguous = by_key["ambiguousKey"]
    assert ambiguous.key_resolution_status is (
        CitationKeyResolutionStatus.AMBIGUOUS
    )
    assert len(ambiguous.identity_items) == 2
    assert tuple(
        item.requested_identity_id for item in ambiguous.identity_items
    ) == tuple(
        sorted(item.requested_identity_id for item in ambiguous.identity_items)
    )

    unresolved = by_key["unresolved"]
    assert unresolved.key_resolution_status is (
        CitationKeyResolutionStatus.UNRESOLVED
    )
    assert unresolved.identity_items == ()
    assert result.projection.source_gaps == request.target_snapshot.source_gaps
    assert tuple(item.literal_citekey for item in result.projection.items) == (
        "acceptedKey",
        "aliasOld",
        "ambiguousKey",
        "candidateOnly",
        "unresolved",
    )


def test__projection_and_link_actions__use_base_roles_and_stable_ids() -> None:
    document = _descriptor("accepted")
    observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(document,),
    )
    request = _projection_request(observations=(observation,))
    projector = CitationDocumentProjector()

    result = projector.project(request=request)

    assert issubclass(
        CitationDocumentProjectionRequest,
        DataObjectActionRequest,
    )
    assert issubclass(
        CitationDocumentProjectionResult,
        DataObjectActionResult,
    )
    assert issubclass(CitationDocumentProjection, DataObjectModel)
    assert issubclass(CitationDocumentProjectionItem, DataObjectModel)
    assert issubclass(CitationDocumentProjector, DataObjectActionizer)
    assert projector.action(request=request) == result
    assert result == CitationDocumentProjector().project(
        request=_projection_request(observations=(observation,))
    )
    assert result.projection.contract_id == (
        CITATION_DOCUMENT_PROJECTION_CONTRACT_ID
    )
    assert "@" not in result.projection.contract_id
    assert not hasattr(result.projection, "schema_version")
    assert not hasattr(result.projection, "contract_version")
    request_fields = {
        item.name for item in fields(CitationDocumentProjectionRequest)
    }
    assert "source_document_link_results" in request_fields
    assert "source_document_links" not in request_fields

    item = next(
        value
        for value in result.projection.items
        if value.literal_citekey == "acceptedKey"
    )
    link_request = CitationSourceDocumentLinkRequest(
        projection_result=result,
        item_id=item.item_id,
        identity_item_id=item.identity_items[0].item_id,
        source_document_id=document.source_document_id,
        pre_effect_intent_id="application-intent:synthetic",
    )
    linker = CitationSourceDocumentLinker()
    linked = linker.link(request=link_request)

    assert issubclass(
        CitationSourceDocumentLinkRequest,
        DataObjectActionRequest,
    )
    assert issubclass(
        CitationSourceDocumentLinkResult,
        DataObjectActionResult,
    )
    assert issubclass(CitationSourceDocumentLink, DataObjectModel)
    assert issubclass(CitationSourceDocumentLinker, DataObjectActionizer)
    assert linker.action(request=link_request) == linked
    assert linked == CitationSourceDocumentLinker().link(
        request=CitationSourceDocumentLinkRequest(
            projection_result=result,
            item_id=item.item_id,
            identity_item_id=item.identity_items[0].item_id,
            source_document_id=document.source_document_id,
            pre_effect_intent_id="application-intent:synthetic",
        )
    )
    assert linked.link.identity_projection_id == (
        request.identity_projection.projection_id
    )
    assert linked.link.linkage_basis == (
        "explicit-upload-for-requested-citation"
    )
    assert linked.link.identity_payload()["contract_id"] == (
        CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID
    )
    for limitation in (
        "not-private-processing-admission",
        "not-search-admission",
    ):
        assert limitation in linked.link.limitations
        assert limitation in result.projection.limitations
    assert "@" not in CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID
    with pytest.raises(FrozenInstanceError):
        result.projection.items = ()  # type: ignore[misc]


def test__empty_complete_target_projects_without_fabricated_rows() -> None:
    snapshot, _, identity_projection = _fixture()
    empty_snapshot = CitationTargetSnapshot(
        snapshot_id=_target_id("citation-snapshot", "empty-target"),
        bibliography_source_path=snapshot.bibliography_source_path,
        bibliography_content_identity=snapshot.bibliography_content_identity,
        occurrences=(),
        groups=(),
        bibliography_entries=(),
        source_gaps=(),
        missing_keys=(),
        duplicate_keys=(),
        uncited_keys=(),
    )

    result = CitationDocumentProjector().project(
        request=CitationDocumentProjectionRequest(
            target_snapshot=empty_snapshot,
            bibliography_bindings=(),
            identity_projection=identity_projection,
        )
    )

    assert result.projection.items == ()
    assert result.projection.source_documents == ()
    assert result.projection.source_gaps == ()


def test__document_status__distinguishes_not_evaluated_and_not_observed() -> (
    None
):
    incomplete = _document_observation(
        key="acceptedKey",
        coverage="incomplete",
    )
    complete = _document_observation(
        key="candidateOnly",
        coverage="complete",
        evidence="application-receipt:complete",
    )
    unresolved_complete = _document_observation(
        key="unresolved",
        coverage="complete",
        evidence="application-receipt:unresolved",
    )

    result = CitationDocumentProjector().project(
        request=_projection_request(
            observations=tuple(
                sorted(
                    (incomplete, complete, unresolved_complete),
                    key=lambda item: (
                        item.literal_citekey,
                        item.observation_id,
                    ),
                )
            )
        )
    )
    by_key = {item.literal_citekey: item for item in result.projection.items}

    assert by_key["acceptedKey"].document_status is (
        CitationDocumentAvailabilityStatus.NOT_EVALUATED
    )
    assert by_key["candidateOnly"].document_status is (
        CitationDocumentAvailabilityStatus.NOT_OBSERVED
    )
    assert by_key["unresolved"].document_status is (
        CitationDocumentAvailabilityStatus.NOT_EVALUATED
    )
    assert by_key["aliasOld"].document_status is (
        CitationDocumentAvailabilityStatus.NOT_EVALUATED
    )


def test__document_status__retains_available_ambiguous_and_inaccessible() -> (
    None
):
    available = _descriptor("available")
    first = _descriptor("first")
    second = _descriptor("second")
    observations = (
        _document_observation(
            key="acceptedKey",
            coverage="complete",
            documents=(available,),
            evidence="receipt:available",
        ),
        _document_observation(
            key="ambiguousKey",
            coverage="complete",
            documents=(first, second),
            evidence="receipt:ambiguous",
        ),
        _document_observation(
            key="candidateOnly",
            coverage="incomplete",
            inaccessible=("access-observation:controlled",),
            evidence="receipt:inaccessible",
        ),
    )
    result = CitationDocumentProjector().project(
        request=_projection_request(observations=observations)
    )
    by_key = {item.literal_citekey: item for item in result.projection.items}

    assert by_key["acceptedKey"].document_status is (
        CitationDocumentAvailabilityStatus.AVAILABLE_UNVERIFIED_LINKAGE
    )
    assert by_key["ambiguousKey"].document_status is (
        CitationDocumentAvailabilityStatus.AMBIGUOUS
    )
    assert by_key["candidateOnly"].document_status is (
        CitationDocumentAvailabilityStatus.INACCESSIBLE
    )
    assert set(by_key["ambiguousKey"].source_document_ids) == {
        first.source_document_id,
        second.source_document_id,
    }


def test__link__reprojects_attached_without_ingestion_or_rights_claim() -> None:
    document = _descriptor("attached")
    observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(document,),
    )
    initial = CitationDocumentProjector().project(
        request=_projection_request(observations=(observation,))
    )
    item = next(
        value
        for value in initial.projection.items
        if value.literal_citekey == "acceptedKey"
    )
    linked = CitationSourceDocumentLinker().link(
        request=CitationSourceDocumentLinkRequest(
            projection_result=initial,
            item_id=item.item_id,
            identity_item_id=item.identity_items[0].item_id,
            source_document_id=document.source_document_id,
            pre_effect_intent_id="citation-ingestion-intent:pre-effect",
        )
    )

    final = CitationDocumentProjector().project(
        request=_projection_request(
            observations=(observation,),
            links=(linked,),
        )
    )
    attached = next(
        value
        for value in final.projection.items
        if value.literal_citekey == "acceptedKey"
    )

    assert attached.document_status is (
        CitationDocumentAvailabilityStatus.AVAILABLE_LINKED
    )
    assert attached.source_document_link_ids == (linked.link.link_id,)
    assert linked.link.pre_effect_intent_id == (
        "citation-ingestion-intent:pre-effect"
    )
    protected = {
        "ingestion_status",
        "manuscript_use_status",
        "review_status",
        "rights_status",
        "scientific_support_status",
    }
    assert protected.isdisjoint(
        {item.name for item in fields(CitationSourceDocumentLink)}
    )
    assert protected.isdisjoint(
        {item.name for item in fields(CitationDocumentProjectionItem)}
    )


def test__competing_linked_content_remains_ambiguous() -> None:
    first_document = _descriptor("linked-first")
    second_document = _descriptor("linked-second")
    first_observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(first_document,),
        evidence="receipt:linked-first",
    )
    second_observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(second_document,),
        evidence="receipt:linked-second",
    )

    def linked(
        observation: CitationSourceDocumentObservation,
        document: CitationSourceDocumentDescriptor,
        intent: str,
    ) -> CitationSourceDocumentLinkResult:
        projected = CitationDocumentProjector().project(
            request=_projection_request(observations=(observation,))
        )
        item = next(
            value
            for value in projected.projection.items
            if value.literal_citekey == "acceptedKey"
        )
        return CitationSourceDocumentLinker().link(
            request=CitationSourceDocumentLinkRequest(
                projection_result=projected,
                item_id=item.item_id,
                identity_item_id=item.identity_items[0].item_id,
                source_document_id=document.source_document_id,
                pre_effect_intent_id=intent,
            )
        )

    links = tuple(
        sorted(
            (
                linked(
                    first_observation,
                    first_document,
                    "pre-effect-intent:linked-first",
                ),
                linked(
                    second_observation,
                    second_document,
                    "pre-effect-intent:linked-second",
                ),
            ),
            key=lambda item: item.link.link_id,
        )
    )
    observations = tuple(
        sorted(
            (first_observation, second_observation),
            key=lambda item: (item.literal_citekey, item.observation_id),
        )
    )
    final = CitationDocumentProjector().project(
        request=_projection_request(observations=observations, links=links)
    )
    item = next(
        value
        for value in final.projection.items
        if value.literal_citekey == "acceptedKey"
    )

    assert item.document_status is CitationDocumentAvailabilityStatus.AMBIGUOUS
    assert item.source_document_link_ids == tuple(
        sorted(result.link.link_id for result in links)
    )
    assert set(item.source_document_ids) == {
        first_document.source_document_id,
        second_document.source_document_id,
    }


def test__link__same_inputs_are_idempotent_and_new_intent_is_distinct() -> None:
    document = _descriptor("idempotent")
    observation = _document_observation(
        key="candidateOnly",
        coverage="complete",
        documents=(document,),
    )
    projection = CitationDocumentProjector().project(
        request=_projection_request(observations=(observation,))
    )
    item = next(
        value
        for value in projection.projection.items
        if value.literal_citekey == "candidateOnly"
    )

    def link(intent: str) -> CitationSourceDocumentLinkResult:
        return CitationSourceDocumentLinker().link(
            request=CitationSourceDocumentLinkRequest(
                projection_result=projection,
                item_id=item.item_id,
                identity_item_id=item.identity_items[0].item_id,
                source_document_id=document.source_document_id,
                pre_effect_intent_id=intent,
            )
        )

    first = link("pre-effect-intent:one")
    repeated = link("pre-effect-intent:one")
    distinct = link("pre-effect-intent:two")

    assert first == repeated
    assert first.link.link_id == repeated.link.link_id
    assert distinct.link.link_id != first.link.link_id


def test__link__requires_resolved_identity_and_unambiguous_document() -> None:
    first = _descriptor("ambiguous-first")
    second = _descriptor("ambiguous-second")
    observations = tuple(
        sorted(
            (
                _document_observation(
                    key="ambiguousKey",
                    coverage="complete",
                    documents=(first,),
                    evidence="receipt:identity-ambiguous",
                ),
                _document_observation(
                    key="acceptedKey",
                    coverage="complete",
                    documents=(second, first),
                    evidence="receipt:document-ambiguous",
                ),
            ),
            key=lambda item: (item.literal_citekey, item.observation_id),
        )
    )
    projection = CitationDocumentProjector().project(
        request=_projection_request(observations=observations)
    )
    by_key = {
        item.literal_citekey: item for item in projection.projection.items
    }

    with pytest.raises(ValueError, match="resolved identity"):
        CitationSourceDocumentLinkRequest(
            projection_result=projection,
            item_id=by_key["ambiguousKey"].item_id,
            identity_item_id=by_key["ambiguousKey"].identity_items[0].item_id,
            source_document_id=first.source_document_id,
            pre_effect_intent_id="pre-effect-intent:ambiguous-identity",
        )
    with pytest.raises(ValueError, match="not linkable"):
        CitationSourceDocumentLinkRequest(
            projection_result=projection,
            item_id=by_key["acceptedKey"].item_id,
            identity_item_id=by_key["acceptedKey"].identity_items[0].item_id,
            source_document_id=first.source_document_id,
            pre_effect_intent_id="pre-effect-intent:ambiguous-document",
        )


def test__projection__rejects_stale_or_mismatched_link() -> None:
    document = _descriptor("stale")
    observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(document,),
    )
    initial = CitationDocumentProjector().project(
        request=_projection_request(observations=(observation,))
    )
    item = next(
        value
        for value in initial.projection.items
        if value.literal_citekey == "acceptedKey"
    )
    link_result = CitationSourceDocumentLinker().link(
        request=CitationSourceDocumentLinkRequest(
            projection_result=initial,
            item_id=item.item_id,
            identity_item_id=item.identity_items[0].item_id,
            source_document_id=document.source_document_id,
            pre_effect_intent_id="pre-effect-intent:stale",
        )
    )

    changed_link = copy.copy(link_result.link)
    object.__setattr__(changed_link, "identity_item_id", "different-item")
    changed_result = copy.copy(link_result)
    object.__setattr__(changed_result, "link", changed_link)
    with pytest.raises(ValueError, match="identity"):
        CitationDocumentProjectionRequest(
            target_snapshot=_fixture()[0],
            bibliography_bindings=_fixture()[1],
            identity_projection=_fixture()[2],
            document_observations=(observation,),
            source_document_link_results=(changed_result,),
        )

    other_observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(_descriptor("different"),),
        evidence="receipt:different",
    )
    request = _projection_request(
        observations=(other_observation,),
        links=(link_result,),
    )
    with pytest.raises(ValueError, match="descriptor is stale"):
        CitationDocumentProjector().project(request=request)


def test__requests__reject_forged_projection_and_identity_replay() -> None:
    document = _descriptor("forged")
    observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(document,),
    )
    result = CitationDocumentProjector().project(
        request=_projection_request(observations=(observation,))
    )
    forged_projection = copy.copy(result.projection)
    object.__setattr__(
        forged_projection,
        "projection_id",
        "citation-document-projection:sha256:" + "0" * 64,
    )
    forged_result = copy.copy(result)
    object.__setattr__(forged_result, "projection", forged_projection)
    item = next(
        value
        for value in result.projection.items
        if value.literal_citekey == "acceptedKey"
    )
    with pytest.raises(ValueError, match="projection identity"):
        CitationSourceDocumentLinkRequest(
            projection_result=forged_result,
            item_id=item.item_id,
            identity_item_id=item.identity_items[0].item_id,
            source_document_id=document.source_document_id,
            pre_effect_intent_id="pre-effect-intent:forged",
        )

    snapshot, bindings, identity_projection = _fixture()
    forged_identity = copy.copy(identity_projection)
    object.__setattr__(forged_identity, "active_reference_ids", ())
    with pytest.raises(ValueError, match="does not match replay"):
        CitationDocumentProjectionRequest(
            target_snapshot=snapshot,
            bibliography_bindings=bindings,
            identity_projection=forged_identity,
        )


def test__rehashed_cross_key_projection_forgery_fails_replay() -> None:
    document = _descriptor("cross-key-forgery")
    observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(document,),
        evidence="receipt:cross-key-forgery",
    )
    request = _projection_request(observations=(observation,))
    valid = CitationDocumentProjector().project(request=request)
    by_key = {item.literal_citekey: item for item in valid.projection.items}
    forged_item = replace(
        by_key["acceptedKey"],
        identity_items=by_key["candidateOnly"].identity_items,
    )
    forged_items = tuple(
        forged_item if item.literal_citekey == "acceptedKey" else item
        for item in valid.projection.items
    )
    payload = valid.projection.identity_payload()
    payload["item_ids"] = [item.item_id for item in forged_items]
    forged_projection = replace(
        valid.projection,
        items=forged_items,
        projection_id=_canonical_id(
            "citation-document-projection",
            payload,
        ),
    )

    with pytest.raises(ValueError, match="projector replay"):
        CitationDocumentProjectionResult(
            request=request,
            projection=forged_projection,
        )


def test__rehashed_link_lineage_forgery_fails_replay() -> None:
    document = _descriptor("link-lineage-forgery")
    observation = _document_observation(
        key="acceptedKey",
        coverage="complete",
        documents=(document,),
        evidence="receipt:link-lineage-forgery",
    )
    projection = CitationDocumentProjector().project(
        request=_projection_request(observations=(observation,))
    )
    item = next(
        value
        for value in projection.projection.items
        if value.literal_citekey == "acceptedKey"
    )
    valid = CitationSourceDocumentLinker().link(
        request=CitationSourceDocumentLinkRequest(
            projection_result=projection,
            item_id=item.item_id,
            identity_item_id=item.identity_items[0].item_id,
            source_document_id=document.source_document_id,
            pre_effect_intent_id="pre-effect-intent:lineage-forgery",
        )
    )
    payload = valid.link.identity_payload()
    payload.update(
        {
            "creating_request_id": "forged-request",
            "prior_projection_id": "forged-projection",
            "prior_item_id": "forged-item",
        }
    )
    forged_link = replace(
        valid.link,
        creating_request_id="forged-request",
        prior_projection_id="forged-projection",
        prior_item_id="forged-item",
        link_id=_canonical_id("citation-source-document-link", payload),
    )

    with pytest.raises(ValueError, match="linker replay"):
        CitationSourceDocumentLinkResult(
            request=valid.request,
            link=forged_link,
        )


def test__binding__rejects_reduced_or_mismatched_entry_evidence() -> None:
    _, bindings, _ = _fixture()
    binding = bindings[0]
    changed_entry = CitationTargetBibliographyEntry(
        entry_id=binding.entry.entry_id,
        entry_index=binding.entry.entry_index,
        key=binding.entry.key,
        entry_type=binding.entry.entry_type,
        locator=binding.entry.locator,
        entry_content_identity=CitationContentIdentity(
            algorithm="sha256",
            digest="0" * 64,
            byte_count=binding.entry.entry_content_identity.byte_count,
        ),
        source_bibliography_observation_id=None,
    )
    with pytest.raises(ValueError, match="verbatim entry conflicts"):
        CitationBibliographyObservationBinding(
            entry=changed_entry,
            observation=binding.observation,
        )


def test__snapshot__rejects_order_partition_and_derived_set_drift() -> None:
    snapshot, _, _ = _fixture()
    with pytest.raises(ValueError, match="groups are not canonical"):
        CitationTargetSnapshot(
            snapshot_id=snapshot.snapshot_id,
            bibliography_source_path=snapshot.bibliography_source_path,
            bibliography_content_identity=snapshot.bibliography_content_identity,
            occurrences=snapshot.occurrences,
            groups=tuple(reversed(snapshot.groups)),
            bibliography_entries=snapshot.bibliography_entries,
            source_gaps=snapshot.source_gaps,
            missing_keys=snapshot.missing_keys,
            duplicate_keys=snapshot.duplicate_keys,
            uncited_keys=snapshot.uncited_keys,
        )
    with pytest.raises(ValueError, match="key sets conflict"):
        CitationTargetSnapshot(
            snapshot_id=snapshot.snapshot_id,
            bibliography_source_path=snapshot.bibliography_source_path,
            bibliography_content_identity=snapshot.bibliography_content_identity,
            occurrences=snapshot.occurrences,
            groups=snapshot.groups,
            bibliography_entries=snapshot.bibliography_entries,
            source_gaps=snapshot.source_gaps,
            missing_keys=(),
            duplicate_keys=snapshot.duplicate_keys,
            uncited_keys=snapshot.uncited_keys,
        )


def test__bounds_and_canonical_input_order_fail_closed() -> None:
    with pytest.raises(ValueError, match="text limit"):
        CitationSourceDocumentDescriptor(
            source_document_id="x" * 513,
            sha256="0" * 64,
            byte_size=1,
        )
    snapshot, _, _ = _fixture()
    with pytest.raises(TypeError, match="target occurrences"):
        CitationTargetSnapshot(
            snapshot_id=snapshot.snapshot_id,
            bibliography_source_path=snapshot.bibliography_source_path,
            bibliography_content_identity=snapshot.bibliography_content_identity,
            occurrences=(snapshot.occurrences[0],)
            * (CITATION_DOCUMENT_MAX_OCCURRENCES + 1),
            groups=snapshot.groups,
            bibliography_entries=snapshot.bibliography_entries,
            source_gaps=snapshot.source_gaps,
            missing_keys=snapshot.missing_keys,
            duplicate_keys=snapshot.duplicate_keys,
            uncited_keys=snapshot.uncited_keys,
        )
    half_record_limit = CITATION_DOCUMENT_MAX_TARGET_RECORDS // 2
    with pytest.raises(ValueError, match="aggregate record count"):
        CitationTargetSnapshot(
            snapshot_id=snapshot.snapshot_id,
            bibliography_source_path=snapshot.bibliography_source_path,
            bibliography_content_identity=snapshot.bibliography_content_identity,
            occurrences=(),
            groups=(),
            bibliography_entries=(snapshot.bibliography_entries[0],)
            * half_record_limit,
            source_gaps=(snapshot.source_gaps[0],) * (half_record_limit + 1),
            missing_keys=(),
            duplicate_keys=(),
            uncited_keys=(),
        )
    descriptor = _descriptor("too-many")
    with pytest.raises(TypeError, match="descriptors"):
        CitationSourceDocumentObservation(
            target_snapshot_id=snapshot.snapshot_id,
            literal_citekey="acceptedKey",
            coverage_status="complete",
            source_documents=(descriptor,)
            * (CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY + 1),
            inaccessible_evidence_ids=(),
            evidence_id="receipt:too-many",
        )
    first = _document_observation(
        key="acceptedKey",
        coverage="complete",
        evidence="z-evidence",
    )
    second = _document_observation(
        key="acceptedKey",
        coverage="complete",
        evidence="a-evidence",
    )
    observations = tuple(
        sorted(
            (first, second),
            key=lambda item: (item.literal_citekey, item.observation_id),
        )
    )
    with pytest.raises(ValueError, match="not canonical"):
        _projection_request(observations=tuple(reversed(observations)))


def test__hard_byte_and_evidence_bounds_hold_at_the_boundary() -> None:
    with pytest.raises(ValueError, match="byte count"):
        CitationContentIdentity(
            algorithm="sha256",
            digest="0" * 64,
            byte_count=0,
        )
    CitationContentIdentity(
        algorithm="sha256",
        digest="0" * 64,
        byte_count=CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES,
    )
    with pytest.raises(ValueError, match="byte count"):
        CitationContentIdentity(
            algorithm="sha256",
            digest="0" * 64,
            byte_count=CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES + 1,
        )
    with pytest.raises(ValueError, match="occurrence indexes"):
        CitationTargetGroup(
            group_id=_target_id("citation-group", "too-many-occurrences"),
            group_index=0,
            key="tooManyOccurrences",
            occurrence_indexes=tuple(
                range(CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD + 1)
            ),
            direct_occurrence_count=(
                CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD + 1
            ),
            generated_occurrence_count=0,
            bibliography_entry_index=None,
        )

    CitationSourceDocumentDescriptor(
        source_document_id="application-source:max-pdf",
        sha256="0" * 64,
        byte_size=CITATION_DOCUMENT_MAX_PDF_BYTES,
    )
    with pytest.raises(ValueError, match="byte size"):
        CitationSourceDocumentDescriptor(
            source_document_id="application-source:oversize-pdf",
            sha256="0" * 64,
            byte_size=CITATION_DOCUMENT_MAX_PDF_BYTES + 1,
        )

    snapshot, _, _ = _fixture()
    evidence_ids = tuple(
        f"evidence:{index:03d}"
        for index in range(CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY)
    )
    CitationSourceDocumentObservation(
        target_snapshot_id=snapshot.snapshot_id,
        literal_citekey="acceptedKey",
        coverage_status="complete",
        source_documents=(),
        inaccessible_evidence_ids=evidence_ids,
        evidence_id="receipt:evidence-boundary",
    )
    with pytest.raises(ValueError, match="not canonical"):
        CitationSourceDocumentObservation(
            target_snapshot_id=snapshot.snapshot_id,
            literal_citekey="acceptedKey",
            coverage_status="complete",
            source_documents=(),
            inaccessible_evidence_ids=(
                *evidence_ids,
                "evidence:overflow",
            ),
            evidence_id="receipt:evidence-overflow",
        )

    CitationTargetSnapshot(
        snapshot_id=_target_id("citation-snapshot", "path-boundary"),
        bibliography_source_path=("a" * CITATION_DOCUMENT_MAX_TEXT_BYTES),
        bibliography_content_identity=_content(b"%"),
        occurrences=(),
        groups=(),
        bibliography_entries=(),
        source_gaps=(),
        missing_keys=(),
        duplicate_keys=(),
        uncited_keys=(),
    )
    with pytest.raises(ValueError, match="text limit"):
        CitationTargetSnapshot(
            snapshot_id=_target_id("citation-snapshot", "path-overflow"),
            bibliography_source_path=(
                "a" * (CITATION_DOCUMENT_MAX_TEXT_BYTES + 1)
            ),
            bibliography_content_identity=_content(b"%"),
            occurrences=(),
            groups=(),
            bibliography_entries=(),
            source_gaps=(),
            missing_keys=(),
            duplicate_keys=(),
            uncited_keys=(),
        )

    large_identity = CitationContentIdentity(
        algorithm="sha256",
        digest="1" * 64,
        byte_count=(
            CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES // 2 + 1
        ),
    )
    large_gaps = tuple(
        CitationTargetSourceGap(
            source_gap_id=_target_id("citation-gap", f"large:{index}"),
            source_gap_index=index,
            locator=CitationSourceLocator(
                source_path=f"large-{index}.tex",
                source_content_identity=large_identity,
                include_index=index,
                byte_start=0,
                byte_end=1,
                line=1,
                column=1,
            ),
            reason="placeholder_identifier",
            placeholder_identifier=f"large-placeholder-{index}",
        )
        for index in range(2)
    )
    with pytest.raises(ValueError, match="aggregate source bytes"):
        CitationTargetSnapshot(
            snapshot_id=_target_id("citation-snapshot", "aggregate-overflow"),
            bibliography_source_path="references.bib",
            bibliography_content_identity=_content(b"%"),
            occurrences=(),
            groups=(),
            bibliography_entries=(),
            source_gaps=large_gaps,
            missing_keys=(),
            duplicate_keys=(),
            uncited_keys=(),
        )

    empty_payload_bytes = len(
        json.dumps(
            {"value": ""},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    boundary_value = "x" * (
        CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES - empty_payload_bytes
    )
    stable_id("boundary", {"value": boundary_value})
    with pytest.raises(ValueError, match="payload exceeds"):
        stable_id("boundary", {"value": boundary_value + "x"})


def test__request_rejects_per_key_and_aggregate_evidence_overflow() -> None:
    per_key = tuple(
        sorted(
            (
                _document_observation(
                    key="acceptedKey",
                    coverage="incomplete",
                    evidence=f"receipt:per-key:{index:03d}",
                )
                for index in range(
                    CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY + 1
                )
            ),
            key=lambda item: (item.literal_citekey, item.observation_id),
        )
    )
    with pytest.raises(ValueError, match="per-key limit"):
        _projection_request(observations=per_key)

    documents = tuple(
        sorted(
            (
                _descriptor(f"aggregate:{index:03d}")
                for index in range(CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY)
            ),
            key=lambda item: item.descriptor_id,
        )
    )
    aggregate_documents = tuple(
        sorted(
            (
                _document_observation(
                    key="acceptedKey",
                    coverage="incomplete",
                    documents=documents,
                    evidence=f"receipt:aggregate-documents:{index:03d}",
                )
                for index in range(
                    CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS
                    // CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY
                    + 1
                )
            ),
            key=lambda item: (item.literal_citekey, item.observation_id),
        )
    )
    with pytest.raises(ValueError, match="aggregate exceeds"):
        _projection_request(observations=aggregate_documents)

    evidence_ids = tuple(
        f"evidence:{index:03d}"
        for index in range(CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY)
    )
    aggregate_inaccessible = tuple(
        sorted(
            (
                _document_observation(
                    key="acceptedKey",
                    coverage="incomplete",
                    inaccessible=evidence_ids,
                    evidence=f"receipt:aggregate-evidence:{index:03d}",
                )
                for index in range(
                    CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS
                    // CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY
                    + 1
                )
            ),
            key=lambda item: (item.literal_citekey, item.observation_id),
        )
    )
    with pytest.raises(ValueError, match="aggregate exceeds"):
        _projection_request(observations=aggregate_inaccessible)
