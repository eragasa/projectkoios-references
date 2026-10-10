"""Course-scoped review of References-owned identity and asset authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, StrEnum
from typing import Protocol, cast

from projectkoios.base import DataObjectActionRequest, DataObjectModel
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyRenderedEntry,
    CandidateBibliographyRenderResult,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import validate_citekey
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
    ReviewActorProvenance,
    ReviewProjection,
    ReviewTransitionKind,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
    StateClaim,
    StateKnowledge,
    StateRecordKind,
    candidate_state_claims,
    replay_reference_state,
)

COURSE_REFERENCE_AUTHORITY_CONTRACT_ID = (
    "projectkoios.references.course-reference-authority@0.1.0"
)
COURSE_REFERENCE_AUTHORITY_PRODUCER = ProducerIdentity(
    "projectkoios.references.course-reference-authority",
    "0.1.0",
)

_MAX_ITEMS = 10_000
_MAX_TEXT = 4_096
_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY_CONTEXT = "projectkoios.references.identity"
_ASSET_CONTEXT = "projectkoios.references.canonical-asset"


class CourseReferenceAuthorityError(ValueError):
    """Raised when queue evidence or an authority transition is invalid."""


class CourseDisplayCitekeyStatus(StrEnum):
    """Mirror the two non-authoritative Courses display statuses."""

    OBSERVED = "observed"
    PROPOSED_NONCANONICAL = "proposed-noncanonical"


class ReferenceRecordMatchKind(StrEnum):
    """Classify observed/rendered byte relations without accepting a record."""

    EXACT_OBSERVED_KEY_AND_BYTES = "exact-observed-key-and-bytes"
    EXACT_RENDERED_KEY_AND_BYTES = "exact-rendered-key-and-bytes"
    SAME_KEY_DIFFERENT_BYTES = "same-key-different-bytes"
    SAME_OBSERVED_BYTES_DIFFERENT_KEY = "same-observed-bytes-different-key"
    SAME_RENDERED_BYTES_DIFFERENT_KEY = "same-rendered-bytes-different-key"


class RuntimeAssetAvailability(StrEnum):
    """Represent a fresh path-free runtime availability observation."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceSelectionEvidence(DataObjectModel):
    """Mirror one Courses-owned selection without deriving its identity."""

    scope_id: str
    selection_id: str
    locator_binding_id: str
    course_id: str
    ordinal: int
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus
    reference_locator: str

    def __post_init__(self) -> None:
        for label, value in (
            ("scope_id", self.scope_id),
            ("selection_id", self.selection_id),
            ("locator_binding_id", self.locator_binding_id),
        ):
            _content_id(value, field=label)
        _bounded(self.course_id, field="course_id")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= _MAX_ITEMS:
            raise CourseReferenceAuthorityError(
                "selection ordinal is outside the supported range"
            )
        validate_citekey(self.display_citekey, field="display citekey")
        if not isinstance(
            self.display_citekey_status,
            CourseDisplayCitekeyStatus,
        ):
            raise TypeError(
                "display_citekey_status must be CourseDisplayCitekeyStatus"
            )
        _content_id(self.reference_locator, field="reference_locator")
        expected_binding_id = _stable_id(
            "course-reference-locator-binding",
            {
                "contract_version": "1.0",
                "display_citekey": self.display_citekey,
                "display_citekey_status": self.display_citekey_status,
                "ordinal": self.ordinal,
                "reference_locator": self.reference_locator,
                "reference_owner": "projectkoios-references",
            },
        )
        if self.locator_binding_id != expected_binding_id:
            raise CourseReferenceAuthorityError(
                "locator binding differs from the Courses contract"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedCandidateEntry(DataObjectModel):
    """Expose source observation provenance with no source path."""

    observation_id: str
    source_id: str
    asserted_source_revision: str | None
    bibliography_sha256: str
    bibliography_byte_size: int
    entry_index: int
    observed_citekey: str
    entry_sha256: str
    entry_byte_size: int

    def __post_init__(self) -> None:
        _content_id(self.observation_id, field="observation_id")
        _bounded(self.source_id, field="source_id")
        if self.asserted_source_revision is not None:
            _bounded(
                self.asserted_source_revision,
                field="asserted_source_revision",
            )
        _sha256(self.bibliography_sha256, field="bibliography_sha256")
        if (
            type(self.bibliography_byte_size) is not int
            or self.bibliography_byte_size <= 0
        ):
            raise CourseReferenceAuthorityError(
                "bibliography byte size must be positive"
            )
        if type(self.entry_index) is not int or self.entry_index < 0:
            raise CourseReferenceAuthorityError(
                "entry index must be nonnegative"
            )
        validate_citekey(self.observed_citekey, field="observed citekey")
        _sha256(self.entry_sha256, field="entry_sha256")
        if type(self.entry_byte_size) is not int or self.entry_byte_size <= 0:
            raise CourseReferenceAuthorityError(
                "entry byte size must be positive"
            )

    @classmethod
    def from_observation(
        cls, observation: SourceBibliographyObservation
    ) -> ObservedCandidateEntry:
        """Remove the private source path from one exact observation."""
        return cls(
            observation_id=observation.observation_id,
            source_id=observation.source_id,
            asserted_source_revision=observation.asserted_source_revision,
            bibliography_sha256=observation.bibliography_sha256,
            bibliography_byte_size=observation.bibliography_byte_size,
            entry_index=observation.entry_index,
            observed_citekey=observation.observed_citekey,
            entry_sha256=hashlib.sha256(
                observation.verbatim_entry.encode("utf-8")
            ).hexdigest(),
            entry_byte_size=len(observation.verbatim_entry.encode("utf-8")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedCandidateEntryEvidence(DataObjectModel):
    """Expose a rendered entry's metadata and identity without its bytes."""

    entry_id: str
    citekey: str
    entry_type: str
    normalized_fields: tuple[tuple[str, str], ...]
    source_observation_ids: tuple[str, ...]
    rendered_sha256: str
    rendered_byte_size: int

    def __post_init__(self) -> None:
        _content_id(self.entry_id, field="entry_id")
        validate_citekey(self.citekey)
        _bounded(self.entry_type, field="entry_type")
        if not isinstance(self.normalized_fields, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or any(type(value) is not str for value in item)
            for item in self.normalized_fields
        ):
            raise TypeError("normalized_fields must be string pairs")
        _content_ids(
            self.source_observation_ids,
            field="source_observation_ids",
        )
        _sha256(self.rendered_sha256, field="rendered_sha256")
        if (
            type(self.rendered_byte_size) is not int
            or self.rendered_byte_size <= 0
        ):
            raise CourseReferenceAuthorityError(
                "rendered entry byte size must be positive"
            )

    @classmethod
    def from_rendered(
        cls, entry: CandidateBibliographyRenderedEntry
    ) -> RenderedCandidateEntryEvidence:
        """Remove the rendered bytes while retaining exact byte identity."""
        return cls(
            entry_id=entry.entry_id,
            citekey=entry.citekey,
            entry_type=entry.entry_type,
            normalized_fields=entry.normalized_fields,
            source_observation_ids=entry.source_observation_ids,
            rendered_sha256=hashlib.sha256(entry.rendered_entry).hexdigest(),
            rendered_byte_size=len(entry.rendered_entry),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRecordDiscrepancy(DataObjectModel):
    """Retain a non-authoritative exact record solely for comparison."""

    citekey: str
    bibtex_entry: str
    authority_status: str = "non-authoritative-discrepancy-observation"
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        _bounded_multiline(
            self.bibtex_entry,
            field="bibtex_entry",
            maximum=262_144,
        )
        if self.authority_status != (
            "non-authoritative-discrepancy-observation"
        ):
            raise CourseReferenceAuthorityError(
                "record discrepancy cannot claim accepted authority"
            )
        object.__setattr__(
            self,
            "record_id",
            _stable_id(
                "reference-record-observation",
                {
                    "authority_status": self.authority_status,
                    "bibtex_entry": self.bibtex_entry,
                    "citekey": self.citekey,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRecordMatch(DataObjectModel):
    """Describe a discrepancy relation without exposing record bytes."""

    record_id: str
    citekey: str
    bibtex_sha256: str
    bibtex_byte_size: int
    authority_status: str
    kind: ReferenceRecordMatchKind

    def __post_init__(self) -> None:
        _content_id(self.record_id, field="record_id")
        validate_citekey(self.citekey)
        _sha256(self.bibtex_sha256, field="bibtex_sha256")
        if type(self.bibtex_byte_size) is not int or self.bibtex_byte_size <= 0:
            raise CourseReferenceAuthorityError(
                "record byte size must be positive"
            )
        if self.authority_status != (
            "non-authoritative-discrepancy-observation"
        ):
            raise CourseReferenceAuthorityError(
                "record match cannot claim accepted authority"
            )
        if not isinstance(self.kind, ReferenceRecordMatchKind):
            raise TypeError("kind must be a ReferenceRecordMatchKind")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAssetAuthorityEvidence(DataObjectModel):
    """Expose path-free asset, runtime, document, and ingestion evidence."""

    candidate_id: str
    asset_observation_id: str
    sha256: str
    byte_size: int
    rights_status: str
    asset_status: str
    runtime_availability: RuntimeAssetAvailability
    runtime_evidence_id: str | None = None
    document_binding_ids: tuple[str, ...] = ()
    ingestion_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _content_id(self.candidate_id, field="candidate_id")
        _content_id(
            self.asset_observation_id,
            field="asset_observation_id",
        )
        _sha256(self.sha256, field="asset sha256")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise CourseReferenceAuthorityError(
                "asset byte size must be nonnegative"
            )
        _bounded(self.rights_status, field="rights_status")
        _bounded(self.asset_status, field="asset_status")
        if not isinstance(self.runtime_availability, RuntimeAssetAvailability):
            raise TypeError(
                "runtime_availability must be RuntimeAssetAvailability"
            )
        if self.runtime_availability is RuntimeAssetAvailability.UNKNOWN:
            if self.runtime_evidence_id is not None:
                raise CourseReferenceAuthorityError(
                    "unknown availability cannot cite runtime evidence"
                )
        elif self.runtime_evidence_id is None:
            raise CourseReferenceAuthorityError(
                "known runtime availability requires evidence"
            )
        if self.runtime_evidence_id is not None:
            _content_id(
                self.runtime_evidence_id,
                field="runtime_evidence_id",
            )
        _content_ids(self.document_binding_ids, field="document_binding_ids")
        _content_ids(
            self.ingestion_evidence_ids,
            field="ingestion_evidence_ids",
        )

    @classmethod
    def from_asset(
        cls,
        asset: SourceAssetRecord,
        *,
        runtime_availability: RuntimeAssetAvailability = (
            RuntimeAssetAvailability.UNKNOWN
        ),
        runtime_evidence_id: str | None = None,
        document_binding_ids: tuple[str, ...] = (),
        ingestion_evidence_ids: tuple[str, ...] = (),
    ) -> ReferenceAssetAuthorityEvidence:
        """Derive an opaque identity while omitting root and relative path."""
        if type(asset) is not SourceAssetRecord:
            raise TypeError("asset must be a SourceAssetRecord")
        return cls(
            candidate_id=asset.candidate_id,
            asset_observation_id=_stable_id(
                "catalog-asset-observation",
                asdict(asset),
            ),
            sha256=asset.sha256,
            byte_size=asset.byte_size,
            rights_status=asset.rights_status,
            asset_status=asset.asset_status,
            runtime_availability=runtime_availability,
            runtime_evidence_id=runtime_evidence_id,
            document_binding_ids=tuple(sorted(document_binding_ids)),
            ingestion_evidence_ids=tuple(sorted(ingestion_evidence_ids)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ActiveReferenceAuthority(DataObjectModel):
    """Path-free active identity and optional source-asset authority."""

    candidate_id: str
    state_projection_id: str
    bibliographic_work_id: str
    active_citekey: str
    alias_citekeys: tuple[str, ...]
    identity_decision_id: str
    source_asset_id: str | None
    canonical_asset_decision_id: str | None
    authority_binding_id: str | None

    def __post_init__(self) -> None:
        for label, value in (
            ("candidate_id", self.candidate_id),
            ("state_projection_id", self.state_projection_id),
            ("bibliographic_work_id", self.bibliographic_work_id),
            ("identity_decision_id", self.identity_decision_id),
        ):
            _content_id(value, field=label)
        validate_citekey(self.active_citekey, field="active citekey")
        _citekeys(self.alias_citekeys, field="alias citekeys")
        if self.active_citekey in self.alias_citekeys:
            raise CourseReferenceAuthorityError(
                "active citekey cannot also be an alias"
            )
        optional = (
            self.source_asset_id,
            self.canonical_asset_decision_id,
            self.authority_binding_id,
        )
        if any(value is None for value in optional) and any(
            value is not None for value in optional
        ):
            raise CourseReferenceAuthorityError(
                "source-asset authority must be complete or absent"
            )
        for optional_value in optional:
            if optional_value is not None:
                _content_id(
                    optional_value,
                    field="source-asset authority identity",
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentReviewDecisionHead(DataObjectModel):
    """Expose a decision head without rationale or private evidence details."""

    decision_id: str
    subject_id: str
    context_id: str
    dimension: HumanReviewDimension
    decision: str
    actor_id: str
    authority_scope: str
    actor_verification_record_id: str
    decided_at: str

    def __post_init__(self) -> None:
        _content_id(self.decision_id, field="decision_id")
        _content_id(self.subject_id, field="subject_id")
        _bounded(self.context_id, field="context_id")
        if self.dimension not in {
            HumanReviewDimension.REFERENCE_IDENTITY,
            HumanReviewDimension.CANONICAL_ASSET,
        }:
            raise CourseReferenceAuthorityError(
                "queue decision head has an unsupported dimension"
            )
        allowed_decisions = {
            HumanReviewDimension.REFERENCE_IDENTITY: {
                item.value for item in ReferenceIdentityDecision
            },
            HumanReviewDimension.CANONICAL_ASSET: {
                item.value for item in CanonicalAssetDecision
            },
        }
        expected_scopes = {
            HumanReviewDimension.REFERENCE_IDENTITY: (
                "reference-identity-curator"
            ),
            HumanReviewDimension.CANONICAL_ASSET: ("canonical-asset-curator"),
        }
        if self.decision not in allowed_decisions[self.dimension]:
            raise CourseReferenceAuthorityError(
                "queue decision is invalid for its dimension"
            )
        _bounded(self.actor_id, field="actor_id")
        if "/" in self.actor_id or "\\" in self.actor_id:
            raise CourseReferenceAuthorityError(
                "queue actor ID cannot contain a filesystem separator"
            )
        if self.authority_scope != expected_scopes[self.dimension]:
            raise CourseReferenceAuthorityError(
                "queue decision has the wrong authority scope"
            )
        _content_id(
            self.actor_verification_record_id,
            field="actor_verification_record_id",
        )
        _bounded(self.decided_at, field="decided_at")

    @classmethod
    def from_decision(
        cls, decision: HumanReviewDecision
    ) -> CurrentReviewDecisionHead:
        """Remove free-text rationale and the complete evidence list."""
        return cls(
            decision_id=decision.decision_id,
            subject_id=decision.subject_id,
            context_id=decision.context_id,
            dimension=decision.dimension,
            decision=decision.decision,
            actor_id=decision.actor.actor_id,
            authority_scope=decision.actor.authority_scope.value,
            actor_verification_record_id=(
                decision.actor.verification_record_id
            ),
            decided_at=decision.decided_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueueRequest(DataObjectActionRequest):
    """Bind exact Courses scope and current References evidence."""

    selections: tuple[CourseReferenceSelectionEvidence, ...]
    render_result: CandidateBibliographyRenderResult
    candidates: tuple[ReferenceCandidate, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    review_projection: ReviewProjection
    state_projections: tuple[ReferenceStateProjection, ...]
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        _typed_tuple(
            self.selections,
            CourseReferenceSelectionEvidence,
            field="selections",
            nonempty=True,
        )
        if len(self.selections) > _MAX_ITEMS:
            raise CourseReferenceAuthorityError("selection limit exceeded")
        if type(self.render_result) is not CandidateBibliographyRenderResult:
            raise TypeError(
                "render_result must be CandidateBibliographyRenderResult"
            )
        _typed_tuple(
            self.candidates,
            ReferenceCandidate,
            field="candidates",
            nonempty=True,
        )
        _typed_tuple(
            self.record_discrepancies,
            ReferenceRecordDiscrepancy,
            field="record_discrepancies",
        )
        _typed_tuple(
            self.assets,
            ReferenceAssetAuthorityEvidence,
            field="assets",
        )
        if type(self.review_projection) is not ReviewProjection:
            raise TypeError("review_projection must be a ReviewProjection")
        _typed_tuple(
            self.state_projections,
            ReferenceStateProjection,
            field="state_projections",
        )
        for label, values in (
            ("candidates", self.candidates),
            ("record discrepancies", self.record_discrepancies),
            ("assets", self.assets),
            ("state projections", self.state_projections),
        ):
            if len(values) > _MAX_ITEMS:
                raise CourseReferenceAuthorityError(f"{label} limit exceeded")
        scope_ids = {item.scope_id for item in self.selections}
        course_ids = {item.course_id for item in self.selections}
        if len(scope_ids) != 1 or len(course_ids) != 1:
            raise CourseReferenceAuthorityError(
                "selections must share one course scope"
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
                    "asset_observation_ids": tuple(
                        sorted(
                            item.asset_observation_id for item in self.assets
                        )
                    ),
                    "candidate_ids": tuple(
                        sorted(item.candidate_id for item in self.candidates)
                    ),
                    "contract_id": COURSE_REFERENCE_AUTHORITY_CONTRACT_ID,
                    "record_ids": tuple(
                        sorted(
                            item.record_id for item in self.record_discrepancies
                        )
                    ),
                    "render_result_id": self.render_result.result_id,
                    "review_projection_id": (
                        self.review_projection.projection_id
                    ),
                    "selection_ids": tuple(
                        item.selection_id for item in self.selections
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
    candidate: ReferenceCandidate
    observations: tuple[ObservedCandidateEntry, ...]
    rendered_entry: RenderedCandidateEntryEvidence
    record_matches: tuple[ReferenceRecordMatch, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    current_identity_decisions: tuple[CurrentReviewDecisionHead, ...]
    current_asset_decision: CurrentReviewDecisionHead | None
    active_authority: ActiveReferenceAuthority | None
    allowed_identity_actions: tuple[ReferenceIdentityDecision, ...]
    allowed_asset_actions: tuple[CanonicalAssetDecision, ...]
    item_revision_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.selection) is not CourseReferenceSelectionEvidence:
            raise TypeError("selection has an invalid type")
        if type(self.candidate) is not ReferenceCandidate:
            raise TypeError("candidate has an invalid type")
        _typed_tuple(
            self.observations,
            ObservedCandidateEntry,
            field="observations",
            nonempty=True,
        )
        if type(self.rendered_entry) is not RenderedCandidateEntryEvidence:
            raise TypeError("rendered_entry has an invalid type")
        _typed_tuple(
            self.record_matches,
            ReferenceRecordMatch,
            field="record_matches",
        )
        _typed_tuple(
            self.assets,
            ReferenceAssetAuthorityEvidence,
            field="assets",
        )
        _typed_tuple(
            self.current_identity_decisions,
            CurrentReviewDecisionHead,
            field="current_identity_decisions",
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
                    "asset_observation_ids": tuple(
                        item.asset_observation_id for item in self.assets
                    ),
                    "candidate_id": self.candidate.candidate_id,
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
                    "rendered_entry_id": self.rendered_entry.entry_id,
                    "selection_id": self.selection.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueue(DataObjectModel):
    """Deterministic complete queue for one Courses-owned selection scope."""

    request_id: str
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
        for label, value in (
            ("request_id", self.request_id),
            ("scope_id", self.scope_id),
            ("source_export_result_id", self.source_export_result_id),
            ("render_result_id", self.render_result_id),
            ("review_projection_id", self.review_projection_id),
        ):
            _content_id(value, field=label)
        _bounded(self.course_id, field="course_id")
        if self.control_class != "CONTROL":
            raise CourseReferenceAuthorityError(
                "course authority queue must remain a CONTROL queue"
            )
        _typed_tuple(
            self.items,
            CourseReferenceAuthorityQueueItem,
            field="items",
            nonempty=True,
        )
        _typed_tuple(
            self.active_authorities,
            ActiveReferenceAuthority,
            field="active_authorities",
        )
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
                    "scope_id": self.scope_id,
                    "source_export_result_id": self.source_export_result_id,
                    "state_projection_ids": self.state_projection_ids,
                },
            ),
        )

    def item(self, selection_id: str) -> CourseReferenceAuthorityQueueItem:
        """Return one exact queue item or fail closed."""
        for item in self.items:
            if item.selection.selection_id == selection_id:
                return item
        raise CourseReferenceAuthorityError("selection is not in the queue")


class CourseReferenceAuthorityProjector:
    """Project a path-free queue without promoting candidate authority."""

    __slots__ = ()

    def project(
        self, *, request: CourseReferenceAuthorityQueueRequest
    ) -> CourseReferenceAuthorityQueue:
        if type(request) is not CourseReferenceAuthorityQueueRequest:
            raise TypeError(
                "request must be CourseReferenceAuthorityQueueRequest"
            )
        rendered_by_id = {
            item.entry_id: item for item in request.render_result.entries
        }
        candidates = request.candidates
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
        items = []
        for selection in request.selections:
            try:
                rendered = rendered_by_id[selection.reference_locator]
            except KeyError as error:
                raise CourseReferenceAuthorityError(
                    "Courses locator has no rendered References entry"
                ) from error
            if rendered.citekey != selection.display_citekey:
                raise CourseReferenceAuthorityError(
                    "Courses citekey guard differs from References entry"
                )
            matching_candidates = tuple(
                item
                for item in candidates
                if item.proposed_citekey == rendered.citekey
                and set(item.source_observation_ids)
                == set(rendered.source_observation_ids)
            )
            if len(matching_candidates) != 1:
                raise CourseReferenceAuthorityError(
                    "rendered entry does not resolve to exactly one candidate"
                )
            candidate = matching_candidates[0]
            try:
                source_observations = tuple(
                    observations[item]
                    for item in rendered.source_observation_ids
                )
            except KeyError as error:
                raise CourseReferenceAuthorityError(
                    "rendered entry lacks its exact source observation"
                ) from error
            observed = tuple(
                ObservedCandidateEntry.from_observation(item)
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
                CurrentReviewDecisionHead.from_decision(item)
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
                CurrentReviewDecisionHead.from_decision(item)
                for item in current_decisions.values()
                if item.subject_id == candidate.candidate_id
                and item.dimension is HumanReviewDimension.CANONICAL_ASSET
                and item.context_id == _ASSET_CONTEXT
            )
            if len(asset_decisions) > 1:
                raise CourseReferenceAuthorityError(
                    "candidate has multiple current asset decisions"
                )
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
                    candidate=candidate,
                    observations=observed,
                    rendered_entry=(
                        RenderedCandidateEntryEvidence.from_rendered(rendered)
                    ),
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
        selected_locators = {item.selection.reference_locator for item in items}
        if selected_locators != set(rendered_by_id):
            raise CourseReferenceAuthorityError(
                "Courses selections differ from the rendered entry set"
            )
        selected_candidate_ids = {item.candidate.candidate_id for item in items}
        if selected_candidate_ids != {
            item.candidate_id for item in request.candidates
        }:
            raise CourseReferenceAuthorityError(
                "Courses selections differ from the candidate set"
            )
        if any(
            asset.candidate_id not in selected_candidate_ids
            for asset in request.assets
        ):
            raise CourseReferenceAuthorityError(
                "asset evidence is outside the selected candidate set"
            )
        first = request.selections[0]
        return CourseReferenceAuthorityQueue(
            request_id=request.request_id,
            scope_id=first.scope_id,
            course_id=first.course_id,
            items=tuple(items),
            active_authorities=active_authorities,
            source_export_result_id=request.render_result.source_export_result_id,
            render_result_id=request.render_result.result_id,
            review_projection_id=request.review_projection.projection_id,
            state_projection_ids=tuple(
                sorted(item.projection_id for item in request.state_projections)
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendReferenceIdentityDecisionRequest(DataObjectActionRequest):
    """Request one CAS-guarded append to identity authority history."""

    queue: CourseReferenceAuthorityQueue
    selection_id: str
    disposition: ReferenceIdentityDecision
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    expected_item_revision_id: str
    expected_current_decision_id: str | None
    target_state_projection_id: str | None = None
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("queue must be CourseReferenceAuthorityQueue")
        _content_id(self.selection_id, field="selection_id")
        if not isinstance(self.disposition, ReferenceIdentityDecision):
            raise TypeError("disposition must be ReferenceIdentityDecision")
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor must be ReviewActorProvenance")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        _content_id(
            self.expected_item_revision_id,
            field="expected_item_revision_id",
        )
        if self.expected_current_decision_id is not None:
            _content_id(
                self.expected_current_decision_id,
                field="expected_current_decision_id",
            )
        if self.target_state_projection_id is not None:
            _content_id(
                self.target_state_projection_id,
                field="target_state_projection_id",
            )
        item = self.queue.item(self.selection_id)
        if item.item_revision_id != self.expected_item_revision_id:
            raise CourseReferenceAuthorityError(
                "identity request item revision is stale"
            )
        if self.disposition not in item.allowed_identity_actions:
            raise CourseReferenceAuthorityError(
                "identity disposition is not currently allowed"
            )
        needs_target = self.disposition in {
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }
        if needs_target != (self.target_state_projection_id is not None):
            raise CourseReferenceAuthorityError(
                "identity target does not match the disposition"
            )
        if self.target_state_projection_id is not None:
            target = _target_authority(
                self.queue,
                self.target_state_projection_id,
            )
            if (
                self.disposition is ReferenceIdentityDecision.ACCEPT_EXISTING
                and target.active_citekey != item.candidate.proposed_citekey
            ):
                raise CourseReferenceAuthorityError(
                    "accept-existing requires the same active citekey"
                )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "append-reference-identity-decision-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "expected_item_revision_id": (
                        self.expected_item_revision_id
                    ),
                    "queue_id": self.queue.queue_id,
                    "rationale": self.rationale,
                    "selection_id": self.selection_id,
                    "target_state_projection_id": (
                        self.target_state_projection_id
                    ),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendCanonicalAssetDecisionRequest(DataObjectActionRequest):
    """Request a separate CAS-guarded canonical-asset decision."""

    queue: CourseReferenceAuthorityQueue
    selection_id: str
    disposition: CanonicalAssetDecision
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    expected_item_revision_id: str
    expected_current_decision_id: str | None
    selected_asset_observation_id: str | None = None
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("queue must be CourseReferenceAuthorityQueue")
        _content_id(self.selection_id, field="selection_id")
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("disposition must be CanonicalAssetDecision")
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor must be ReviewActorProvenance")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        _content_id(
            self.expected_item_revision_id,
            field="expected_item_revision_id",
        )
        if self.expected_current_decision_id is not None:
            _content_id(
                self.expected_current_decision_id,
                field="expected_current_decision_id",
            )
        if self.selected_asset_observation_id is not None:
            _content_id(
                self.selected_asset_observation_id,
                field="selected_asset_observation_id",
            )
        item = self.queue.item(self.selection_id)
        if item.item_revision_id != self.expected_item_revision_id:
            raise CourseReferenceAuthorityError(
                "asset request item revision is stale"
            )
        if self.disposition not in item.allowed_asset_actions:
            raise CourseReferenceAuthorityError(
                "asset disposition is not currently allowed"
            )
        selecting = self.disposition is CanonicalAssetDecision.AUTHORIZE
        if selecting != (self.selected_asset_observation_id is not None):
            raise CourseReferenceAuthorityError(
                "selected asset does not match the disposition"
            )
        if self.selected_asset_observation_id is not None:
            selected = _asset(item, self.selected_asset_observation_id)
            if (
                selected.runtime_availability
                is not RuntimeAssetAvailability.AVAILABLE
            ):
                raise CourseReferenceAuthorityError(
                    "selected asset is not currently available"
                )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "append-canonical-asset-decision-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "expected_item_revision_id": (
                        self.expected_item_revision_id
                    ),
                    "queue_id": self.queue.queue_id,
                    "rationale": self.rationale,
                    "selected_asset_observation_id": (
                        self.selected_asset_observation_id
                    ),
                    "selection_id": self.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityDecisionResult(DataObjectModel):
    """Report one appended decision and its optional accepted projection."""

    request_id: str
    decision: HumanReviewDecision
    state_projection: ReferenceStateProjection | None
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        _content_id(self.request_id, field="request_id")
        if type(self.decision) is not HumanReviewDecision:
            raise TypeError("decision must be HumanReviewDecision")
        if (
            self.state_projection is not None
            and type(self.state_projection) is not ReferenceStateProjection
        ):
            raise TypeError("state_projection has an invalid type")
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "reference-authority-decision-result",
                {
                    "decision_id": self.decision.decision_id,
                    "request_id": self.request_id,
                    "state_projection_id": (
                        None
                        if self.state_projection is None
                        else self.state_projection.projection_id
                    ),
                },
            ),
        )


class CourseReferenceAuthorityRepository(Protocol):
    """Append candidate evidence, one decision, and projection atomically."""

    def append_course_authority_decision(
        self,
        *,
        candidate: ReferenceCandidate,
        observations: tuple[SourceBibliographyObservation, ...],
        decision: HumanReviewDecision,
        state_projection: ReferenceStateProjection | None,
        expected_current_decision_id: str | None,
        expected_queue_id: str,
        expected_item_revision_id: str,
        expected_review_projection_id: str,
        expected_state_projection_ids: tuple[str, ...],
        expected_asset_observation_ids: tuple[str, ...],
    ) -> None: ...


class ReferenceAuthorityDecisionAppender:
    """Create and atomically append owner decisions with exact CAS evidence."""

    __slots__ = ("_candidates", "_observations", "_repository")

    def __init__(
        self,
        *,
        repository: CourseReferenceAuthorityRepository,
        candidates: tuple[ReferenceCandidate, ...],
        observations: tuple[SourceBibliographyObservation, ...],
    ) -> None:
        self._repository = repository
        self._candidates = {item.candidate_id: item for item in candidates}
        self._observations = {
            item.observation_id: item for item in observations
        }
        if len(self._candidates) != len(candidates):
            raise CourseReferenceAuthorityError("candidate identities repeat")
        if len(self._observations) != len(observations):
            raise CourseReferenceAuthorityError(
                "source observation identities repeat"
            )

    def append_identity(
        self, *, request: AppendReferenceIdentityDecisionRequest
    ) -> ReferenceAuthorityDecisionResult:
        """Append one identity decision without selecting an asset."""
        if type(request) is not AppendReferenceIdentityDecisionRequest:
            raise TypeError("request has an invalid identity request type")
        item = request.queue.item(request.selection_id)
        candidate = self._candidate(item.candidate.candidate_id)
        context = (
            item.selection.course_id
            if request.disposition is ReferenceIdentityDecision.DEFER
            else _IDENTITY_CONTEXT
        )
        current = _current_decision(
            item.current_identity_decisions,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            context_id=context,
        )
        _require_expected_head(current, request.expected_current_decision_id)
        target = (
            None
            if request.target_state_projection_id is None
            else _target_authority(
                request.queue,
                request.target_state_projection_id,
            )
        )
        evidence_ids = {
            request.queue.queue_id,
            request.queue.review_projection_id,
            item.item_revision_id,
            item.selection.scope_id,
            item.selection.selection_id,
            item.selection.locator_binding_id,
            item.rendered_entry.entry_id,
            candidate.candidate_id,
            request.actor.verification_record_id,
            *(entry.observation_id for entry in item.observations),
        }
        if target is not None:
            evidence_ids.update(
                {
                    target.state_projection_id,
                    target.bibliographic_work_id,
                    target.identity_decision_id,
                }
            )
        decision = HumanReviewDecision.create(
            subject_id=candidate.candidate_id,
            context_id=context,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            decision=request.disposition,
            producer=COURSE_REFERENCE_AUTHORITY_PRODUCER,
            transition_kind=(
                ReviewTransitionKind.INITIAL
                if current is None
                else ReviewTransitionKind.SUPERSESSION
            ),
            actor=request.actor,
            evidence_ids=tuple(sorted(evidence_ids)),
            rationale=request.rationale,
            decided_at=request.decided_at,
            supersedes_decision_id=(
                None if current is None else current.decision_id
            ),
        )
        state_projection = None
        if request.disposition in {
            ReferenceIdentityDecision.ACCEPT_NEW,
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }:
            state_projection = _identity_state_projection(
                candidate=candidate,
                decision=decision,
                disposition=request.disposition,
                target=target,
            )
        self._repository.append_course_authority_decision(
            candidate=candidate,
            observations=self._candidate_observations(candidate),
            decision=decision,
            state_projection=state_projection,
            expected_current_decision_id=request.expected_current_decision_id,
            expected_queue_id=request.queue.queue_id,
            expected_item_revision_id=item.item_revision_id,
            expected_review_projection_id=(request.queue.review_projection_id),
            expected_state_projection_ids=request.queue.state_projection_ids,
            expected_asset_observation_ids=tuple(
                item.asset_observation_id for item in item.assets
            ),
        )
        return ReferenceAuthorityDecisionResult(
            request_id=request.request_id,
            decision=decision,
            state_projection=state_projection,
        )

    def append_asset(
        self, *, request: AppendCanonicalAssetDecisionRequest
    ) -> ReferenceAuthorityDecisionResult:
        """Append one asset decision only after accepted identity exists."""
        if type(request) is not AppendCanonicalAssetDecisionRequest:
            raise TypeError("request has an invalid asset request type")
        item = request.queue.item(request.selection_id)
        candidate = self._candidate(item.candidate.candidate_id)
        if item.active_authority is None:
            raise CourseReferenceAuthorityError(
                "asset decision requires accepted identity authority"
            )
        current = item.current_asset_decision
        _require_expected_head(current, request.expected_current_decision_id)
        selected = (
            None
            if request.selected_asset_observation_id is None
            else _asset(item, request.selected_asset_observation_id)
        )
        evidence_ids = {
            request.queue.queue_id,
            request.queue.review_projection_id,
            item.item_revision_id,
            item.selection.scope_id,
            item.selection.selection_id,
            candidate.candidate_id,
            item.active_authority.state_projection_id,
            item.active_authority.bibliographic_work_id,
            item.active_authority.identity_decision_id,
            request.actor.verification_record_id,
            *(asset.asset_observation_id for asset in item.assets),
        }
        if selected is not None:
            evidence_ids.add(selected.asset_observation_id)
            if selected.runtime_evidence_id is not None:
                evidence_ids.add(selected.runtime_evidence_id)
            evidence_ids.update(selected.document_binding_ids)
            evidence_ids.update(selected.ingestion_evidence_ids)
        decision = HumanReviewDecision.create(
            subject_id=candidate.candidate_id,
            context_id=_ASSET_CONTEXT,
            dimension=HumanReviewDimension.CANONICAL_ASSET,
            decision=request.disposition,
            producer=COURSE_REFERENCE_AUTHORITY_PRODUCER,
            transition_kind=(
                ReviewTransitionKind.INITIAL
                if current is None
                else ReviewTransitionKind.SUPERSESSION
            ),
            actor=request.actor,
            evidence_ids=tuple(sorted(evidence_ids)),
            rationale=request.rationale,
            decided_at=request.decided_at,
            supersedes_decision_id=(
                None if current is None else current.decision_id
            ),
        )
        state_projection = None
        if request.disposition is CanonicalAssetDecision.AUTHORIZE:
            assert selected is not None
            identity_decision = _accepted_identity_decision(item)
            state_projection = _asset_state_projection(
                candidate=candidate,
                identity_decision=identity_decision,
                authority=item.active_authority,
                asset_decision=decision,
                asset=selected,
            )
        self._repository.append_course_authority_decision(
            candidate=candidate,
            observations=self._candidate_observations(candidate),
            decision=decision,
            state_projection=state_projection,
            expected_current_decision_id=request.expected_current_decision_id,
            expected_queue_id=request.queue.queue_id,
            expected_item_revision_id=item.item_revision_id,
            expected_review_projection_id=(request.queue.review_projection_id),
            expected_state_projection_ids=request.queue.state_projection_ids,
            expected_asset_observation_ids=tuple(
                item.asset_observation_id for item in item.assets
            ),
        )
        return ReferenceAuthorityDecisionResult(
            request_id=request.request_id,
            decision=decision,
            state_projection=state_projection,
        )

    def _candidate(self, candidate_id: str) -> ReferenceCandidate:
        try:
            return self._candidates[candidate_id]
        except KeyError as error:
            raise CourseReferenceAuthorityError(
                "appender lacks exact candidate evidence"
            ) from error

    def _candidate_observations(
        self, candidate: ReferenceCandidate
    ) -> tuple[SourceBibliographyObservation, ...]:
        try:
            return tuple(
                self._observations[item]
                for item in candidate.source_observation_ids
            )
        except KeyError as error:
            raise CourseReferenceAuthorityError(
                "appender lacks exact source observation evidence"
            ) from error


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityBinding(DataObjectModel):
    """Supply the exact References C authority needed by Search."""

    candidate_id: str
    bibliographic_work_id: str
    reference_identity_status: str
    accepted_citekey: str
    source_asset_id: str
    authority_binding_id: str
    identity_decision_id: str
    canonical_asset_decision_id: str
    authority_evidence_ids: tuple[str, ...]
    state_projection_id: str
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("candidate_id", self.candidate_id),
            ("bibliographic_work_id", self.bibliographic_work_id),
            ("source_asset_id", self.source_asset_id),
            ("authority_binding_id", self.authority_binding_id),
            ("identity_decision_id", self.identity_decision_id),
            (
                "canonical_asset_decision_id",
                self.canonical_asset_decision_id,
            ),
            ("state_projection_id", self.state_projection_id),
        ):
            _content_id(value, field=label)
        if self.reference_identity_status != "accepted":
            raise CourseReferenceAuthorityError(
                "Search authority binding must be explicitly accepted"
            )
        _content_ids(
            self.authority_evidence_ids,
            field="authority_evidence_ids",
        )
        validate_citekey(self.accepted_citekey, field="accepted citekey")
        object.__setattr__(
            self,
            "binding_id",
            _stable_id(
                "search-reference-authority-binding",
                {
                    "accepted_citekey": self.accepted_citekey,
                    "authority_binding_id": self.authority_binding_id,
                    "authority_evidence_ids": self.authority_evidence_ids,
                    "bibliographic_work_id": self.bibliographic_work_id,
                    "candidate_id": self.candidate_id,
                    "canonical_asset_decision_id": (
                        self.canonical_asset_decision_id
                    ),
                    "identity_decision_id": self.identity_decision_id,
                    "reference_identity_status": (
                        self.reference_identity_status
                    ),
                    "source_asset_id": self.source_asset_id,
                    "state_projection_id": self.state_projection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityProjection(DataObjectModel):
    """Return only replay-current complete authority bindings for Search."""

    review_projection_id: str
    bindings: tuple[SearchReferenceAuthorityBinding, ...]
    projection_id: str = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        _content_id(self.review_projection_id, field="review_projection_id")
        _typed_tuple(
            self.bindings,
            SearchReferenceAuthorityBinding,
            field="bindings",
        )
        if tuple(item.binding_id for item in self.bindings) != tuple(
            sorted(item.binding_id for item in self.bindings)
        ):
            raise CourseReferenceAuthorityError(
                "Search authority bindings must use canonical order"
            )
        projection_id = _stable_id(
            "search-reference-authority-projection",
            {
                "binding_ids": tuple(item.binding_id for item in self.bindings),
                "review_projection_id": self.review_projection_id,
            },
        )
        object.__setattr__(self, "projection_id", projection_id)
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "search-reference-authority-result",
                {
                    "contract_id": COURSE_REFERENCE_AUTHORITY_CONTRACT_ID,
                    "projection_id": projection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedCourseReferenceBinding(DataObjectModel):
    """Compose one Courses locator binding with References authority."""

    scope_id: str
    selection_id: str
    locator_binding_id: str
    ordinal: int
    display_citekey: str
    display_citekey_status: CourseDisplayCitekeyStatus
    reference_locator: str
    candidate_id: str
    bibliographic_work_id: str
    accepted_citekey: str
    source_asset_id: str
    identity_decision_id: str
    canonical_asset_decision_id: str
    state_projection_id: str
    authority_binding_id: str
    reviewed_binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("scope_id", self.scope_id),
            ("selection_id", self.selection_id),
            ("locator_binding_id", self.locator_binding_id),
            ("reference_locator", self.reference_locator),
            ("candidate_id", self.candidate_id),
            ("bibliographic_work_id", self.bibliographic_work_id),
            ("source_asset_id", self.source_asset_id),
            ("identity_decision_id", self.identity_decision_id),
            (
                "canonical_asset_decision_id",
                self.canonical_asset_decision_id,
            ),
            ("state_projection_id", self.state_projection_id),
            ("authority_binding_id", self.authority_binding_id),
        ):
            _content_id(value, field=label)
        if type(self.ordinal) is not int or self.ordinal <= 0:
            raise CourseReferenceAuthorityError("binding ordinal is invalid")
        validate_citekey(self.display_citekey, field="display citekey")
        validate_citekey(self.accepted_citekey, field="accepted citekey")
        if not isinstance(
            self.display_citekey_status,
            CourseDisplayCitekeyStatus,
        ):
            raise TypeError("display citekey status is invalid")
        object.__setattr__(
            self,
            "reviewed_binding_id",
            _stable_id(
                "reviewed-course-reference-binding",
                {
                    "accepted_citekey": self.accepted_citekey,
                    "authority_binding_id": self.authority_binding_id,
                    "bibliographic_work_id": self.bibliographic_work_id,
                    "candidate_id": self.candidate_id,
                    "canonical_asset_decision_id": (
                        self.canonical_asset_decision_id
                    ),
                    "display_citekey": self.display_citekey,
                    "display_citekey_status": self.display_citekey_status,
                    "identity_decision_id": self.identity_decision_id,
                    "locator_binding_id": self.locator_binding_id,
                    "ordinal": self.ordinal,
                    "reference_locator": self.reference_locator,
                    "scope_id": self.scope_id,
                    "selection_id": self.selection_id,
                    "source_asset_id": self.source_asset_id,
                    "state_projection_id": self.state_projection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewedCourseReferenceProjection(DataObjectModel):
    """Return the ordered reviewed tuple for API/Courses composition."""

    queue_id: str
    scope_id: str
    course_id: str
    bindings: tuple[ReviewedCourseReferenceBinding, ...]
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        _content_id(self.queue_id, field="queue_id")
        _content_id(self.scope_id, field="scope_id")
        _bounded(self.course_id, field="course_id")
        _typed_tuple(
            self.bindings,
            ReviewedCourseReferenceBinding,
            field="bindings",
            nonempty=True,
        )
        if tuple(item.ordinal for item in self.bindings) != tuple(
            range(1, len(self.bindings) + 1)
        ):
            raise CourseReferenceAuthorityError(
                "reviewed bindings must preserve exact Courses order"
            )
        if any(item.scope_id != self.scope_id for item in self.bindings):
            raise CourseReferenceAuthorityError(
                "reviewed binding scope differs from its projection"
            )
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "reviewed-course-reference-projection",
                {
                    "binding_ids": tuple(
                        item.reviewed_binding_id for item in self.bindings
                    ),
                    "course_id": self.course_id,
                    "queue_id": self.queue_id,
                    "scope_id": self.scope_id,
                },
            ),
        )


def project_reviewed_course_references(
    *, queue: CourseReferenceAuthorityQueue
) -> ReviewedCourseReferenceProjection:
    """Compose an exact tuple only when every selected item has both stages."""
    if type(queue) is not CourseReferenceAuthorityQueue:
        raise TypeError("queue must be CourseReferenceAuthorityQueue")
    bindings = []
    for item in queue.items:
        authority = item.active_authority
        if authority is None or authority.source_asset_id is None:
            raise CourseReferenceAuthorityError(
                "course reference scope is not completely reviewed"
            )
        assert authority.canonical_asset_decision_id is not None
        assert authority.authority_binding_id is not None
        bindings.append(
            ReviewedCourseReferenceBinding(
                scope_id=item.selection.scope_id,
                selection_id=item.selection.selection_id,
                locator_binding_id=item.selection.locator_binding_id,
                ordinal=item.selection.ordinal,
                display_citekey=item.selection.display_citekey,
                display_citekey_status=(item.selection.display_citekey_status),
                reference_locator=item.selection.reference_locator,
                candidate_id=item.candidate.candidate_id,
                bibliographic_work_id=authority.bibliographic_work_id,
                accepted_citekey=authority.active_citekey,
                source_asset_id=authority.source_asset_id,
                identity_decision_id=authority.identity_decision_id,
                canonical_asset_decision_id=(
                    authority.canonical_asset_decision_id
                ),
                state_projection_id=authority.state_projection_id,
                authority_binding_id=authority.authority_binding_id,
            )
        )
    return ReviewedCourseReferenceProjection(
        queue_id=queue.queue_id,
        scope_id=queue.scope_id,
        course_id=queue.course_id,
        bindings=tuple(bindings),
    )


def project_search_reference_authority(
    *,
    review_projection: ReviewProjection,
    state_projections: tuple[ReferenceStateProjection, ...],
) -> SearchReferenceAuthorityProjection:
    """Project only current identity-plus-asset authority; never infer it."""
    active = _active_authorities(state_projections, review_projection)
    projections_by_id = {item.projection_id: item for item in state_projections}
    bindings = tuple(
        sorted(
            (
                SearchReferenceAuthorityBinding(
                    candidate_id=item.candidate_id,
                    bibliographic_work_id=item.bibliographic_work_id,
                    reference_identity_status="accepted",
                    accepted_citekey=item.active_citekey,
                    source_asset_id=cast(str, item.source_asset_id),
                    authority_binding_id=cast(str, item.authority_binding_id),
                    identity_decision_id=item.identity_decision_id,
                    canonical_asset_decision_id=cast(
                        str, item.canonical_asset_decision_id
                    ),
                    authority_evidence_ids=projections_by_id[
                        item.state_projection_id
                    ].authoritative_input_ids,
                    state_projection_id=item.state_projection_id,
                )
                for item in active
                if item.source_asset_id is not None
            ),
            key=lambda item: item.binding_id,
        )
    )
    return SearchReferenceAuthorityProjection(
        review_projection_id=review_projection.projection_id,
        bindings=bindings,
    )


def _identity_state_projection(
    *,
    candidate: ReferenceCandidate,
    decision: HumanReviewDecision,
    disposition: ReferenceIdentityDecision,
    target: ActiveReferenceAuthority | None,
) -> ReferenceStateProjection:
    if disposition is ReferenceIdentityDecision.ACCEPT_NEW:
        work_id = _stable_id(
            "bibliographic-work",
            {
                "candidate_id": candidate.candidate_id,
                "creating_decision_id": decision.decision_id,
            },
        )
        active_citekey = candidate.proposed_citekey
        aliases: tuple[str, ...] = ()
    else:
        if target is None:
            raise CourseReferenceAuthorityError(
                "accepted existing or merged identity requires a target"
            )
        work_id = target.bibliographic_work_id
        active_citekey = target.active_citekey
        aliases = target.alias_citekeys
        if (
            disposition is ReferenceIdentityDecision.MERGE
            and candidate.proposed_citekey != active_citekey
        ):
            aliases = tuple(sorted({*aliases, candidate.proposed_citekey}))
    claims = _candidate_claims_for_acceptance(candidate)
    claims.extend(
        _human_claims(
            decision=decision,
            values=(
                ("identity_status", "accepted"),
                ("bibliographic_work_id", work_id),
                ("active_citekey", active_citekey),
                ("alias_citekeys", aliases),
                ("identity_decision_id", decision.decision_id),
            ),
        )
    )
    authoritative_ids = {
        candidate.candidate_id,
        decision.decision_id,
        *decision.evidence_ids,
    }
    return replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=claims,
        authoritative_input_ids=tuple(sorted(authoritative_ids)),
        exclusions=(
            "canonical asset requires a separate curator decision",
            "claim support is not projected by references",
            "publication is not projected by references",
            "rights clearance is not granted by identity acceptance",
        ),
    )


def _asset_state_projection(
    *,
    candidate: ReferenceCandidate,
    identity_decision: CurrentReviewDecisionHead,
    authority: ActiveReferenceAuthority,
    asset_decision: HumanReviewDecision,
    asset: ReferenceAssetAuthorityEvidence,
) -> ReferenceStateProjection:
    source_asset_id = _stable_id(
        "source-asset",
        {
            "asset_observation_id": asset.asset_observation_id,
            "authorization_decision_id": asset_decision.decision_id,
            "bibliographic_work_id": authority.bibliographic_work_id,
        },
    )
    binding_id = _stable_id(
        "reference-source-asset-binding",
        {
            "asset_observation_id": asset.asset_observation_id,
            "bibliographic_work_id": authority.bibliographic_work_id,
            "candidate_id": candidate.candidate_id,
            "canonical_asset_decision_id": asset_decision.decision_id,
            "identity_decision_id": authority.identity_decision_id,
            "source_asset_id": source_asset_id,
        },
    )
    claims = _candidate_claims_for_acceptance(candidate)
    claims.extend(
        _human_claims(
            decision=identity_decision,
            values=(
                ("identity_status", "accepted"),
                (
                    "bibliographic_work_id",
                    authority.bibliographic_work_id,
                ),
                ("active_citekey", authority.active_citekey),
                ("alias_citekeys", authority.alias_citekeys),
                ("identity_decision_id", authority.identity_decision_id),
            ),
        )
    )
    claims.extend(
        _human_claims(
            decision=asset_decision,
            values=(
                ("source_asset_id", source_asset_id),
                (
                    "canonical_asset_decision_id",
                    asset_decision.decision_id,
                ),
                ("authority_binding_id", binding_id),
            ),
        )
    )
    authoritative_ids = {
        candidate.candidate_id,
        identity_decision.decision_id,
        asset_decision.decision_id,
        *asset_decision.evidence_ids,
    }
    return replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=claims,
        authoritative_input_ids=tuple(sorted(authoritative_ids)),
        exclusions=(
            "asset authorization establishes linkage, not rights clearance",
            "claim support is not projected by references",
            "publication is not projected by references",
        ),
    )


def _candidate_claims_for_acceptance(
    candidate: ReferenceCandidate,
) -> list[StateClaim]:
    return [
        item
        for item in candidate_state_claims(candidate)
        if item.field != "identity_status"
    ]


def _human_claims(
    *,
    decision: HumanReviewDecision | CurrentReviewDecisionHead,
    values: tuple[tuple[str, object], ...],
) -> list[StateClaim]:
    actor_id = (
        decision.actor.actor_id
        if isinstance(decision, HumanReviewDecision)
        else decision.actor_id
    )
    authority_scope = (
        decision.actor.authority_scope.value
        if isinstance(decision, HumanReviewDecision)
        else decision.authority_scope
    )
    verification_record_id = (
        decision.actor.verification_record_id
        if isinstance(decision, HumanReviewDecision)
        else decision.actor_verification_record_id
    )
    return [
        StateClaim(
            subject_id=decision.subject_id,
            field=name,
            knowledge=StateKnowledge.OBSERVED,
            value_json=_canonical_json(value),
            record_kind=StateRecordKind.HUMAN_DECISION,
            authority_owner="projectkoios-references",
            authoritative_input_id=decision.decision_id,
            source_locator=(
                f"course-reference-authority/{decision.dimension.value}/{name}"
            ),
            actor_id=actor_id,
            authority_scope=authority_scope,
            actor_verification_record_id=verification_record_id,
        )
        for name, value in values
    ]


def _record_matches(
    *,
    candidate: ReferenceCandidate,
    rendered: CandidateBibliographyRenderedEntry,
    source_observations: tuple[SourceBibliographyObservation, ...],
    records: tuple[ReferenceRecordDiscrepancy, ...],
) -> tuple[ReferenceRecordMatch, ...]:
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
        proposed_citekey = cast(str, values["proposed_citekey"])
        active_citekey = cast(str, values["active_citekey"])
        work_id = cast(str, values["bibliographic_work_id"])
        aliases = tuple(cast(list[str], values["alias_citekeys"]))
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
            work_id = cast(str, values["bibliographic_work_id"])
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
            bibliographic_work_id=cast(str, values["bibliographic_work_id"]),
            active_citekey=cast(str, values["active_citekey"]),
            alias_citekeys=tuple(cast(list[str], values["alias_citekeys"])),
            identity_decision_id=cast(str, identity_decision_id),
            source_asset_id=cast(str | None, values["source_asset_id"]),
            canonical_asset_decision_id=cast(str | None, asset_decision_id),
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


def _single_projection_value(
    projection: ReferenceStateProjection,
    field_name: str,
) -> object | None:
    item = projection.field(field_name)
    if len(item.values) != 1 or item.values[0].value_json is None:
        return None
    return json.loads(item.values[0].value_json)


def _accepted_identity_decision(
    item: CourseReferenceAuthorityQueueItem,
) -> CurrentReviewDecisionHead:
    if item.active_authority is None:
        raise CourseReferenceAuthorityError("candidate is not accepted")
    for decision in item.current_identity_decisions:
        if decision.decision_id == item.active_authority.identity_decision_id:
            return decision
    raise CourseReferenceAuthorityError(
        "accepted state lacks its current identity decision"
    )


def _current_decision(
    decisions: tuple[CurrentReviewDecisionHead, ...],
    *,
    dimension: HumanReviewDimension,
    context_id: str,
) -> CurrentReviewDecisionHead | None:
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
    actual = None if current is None else current.decision_id
    if actual != expected:
        raise CourseReferenceAuthorityError("decision stream revision is stale")


def _target_authority(
    queue: CourseReferenceAuthorityQueue,
    state_projection_id: str,
) -> ActiveReferenceAuthority:
    for item in queue.active_authorities:
        if item.state_projection_id == state_projection_id:
            return item
    raise CourseReferenceAuthorityError(
        "target is not an active accepted schema-5 projection"
    )


def _asset(
    item: CourseReferenceAuthorityQueueItem,
    observation_id: str,
) -> ReferenceAssetAuthorityEvidence:
    for asset in item.assets:
        if asset.asset_observation_id == observation_id:
            return asset
    raise CourseReferenceAuthorityError(
        "selected asset is not in the current candidate plan"
    )


def _typed_tuple(
    value: object,
    expected: type[object],
    *,
    field: str,
    nonempty: bool = False,
) -> None:
    if not isinstance(value, tuple) or any(
        type(item) is not expected for item in value
    ):
        raise TypeError(f"{field} must be an exact typed tuple")
    if nonempty and not value:
        raise CourseReferenceAuthorityError(f"{field} must be non-empty")


def _unique(values: Iterable[str], *, field: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise CourseReferenceAuthorityError(f"{field} must be unique")


def _bounded(value: str, *, field: str, maximum: int = _MAX_TEXT) -> str:
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


def _bounded_multiline(
    value: str,
    *,
    field: str,
    maximum: int,
) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(
            ord(character) < 0x20 and character not in "\t\n\r"
            for character in value
        )
    ):
        raise CourseReferenceAuthorityError(
            f"{field} must be bounded multiline text"
        )
    return value


def _content_id(value: str, *, field: str) -> str:
    if type(value) is not str or _CONTENT_ID.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} is not a content ID")
    return value


def _content_ids(values: tuple[str, ...], *, field: str) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    for value in values:
        _content_id(value, field=field)
    if values != tuple(sorted(set(values))):
        raise CourseReferenceAuthorityError(
            f"{field} must use unique lexical order"
        )


def _sha256(value: str, *, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} is not SHA-256")
    return value


def _citekeys(values: tuple[str, ...], *, field: str) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    for value in values:
        validate_citekey(value, field=field)
    if values != tuple(sorted(set(values))):
        raise CourseReferenceAuthorityError(
            f"{field} must use unique lexical order"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_id(kind: str, payload: object) -> str:
    encoded = json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: getattr(value, item.name)
            for item in value.__dataclass_fields__.values()
            if item.init
        }
    raise TypeError(f"unsupported identity value: {type(value).__name__}")
