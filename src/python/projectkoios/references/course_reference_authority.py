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


class CourseReferenceSelectionOrigin(StrEnum):
    """Mirror the Courses-owned selection origin."""

    PRESERVED_MANUSCRIPT = "preserved-manuscript"
    DIRECTED_REFERENCE_SCOPE = "directed-reference-scope"


class CourseReferenceRole(StrEnum):
    """Mirror the bounded Courses-owned reference role."""

    MANUSCRIPT_BIBLIOGRAPHY = "manuscript-bibliography"


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


class CourseReferenceItemResolution(StrEnum):
    """Expose left-projection resolution without dropping a Course item."""

    READY = "ready"
    RENDERED_LOCATOR_UNAVAILABLE = "rendered-locator-unavailable"
    DISPLAY_GUARD_MISMATCH = "display-guard-mismatch"
    CANDIDATE_UNAVAILABLE = "candidate-unavailable"
    CANDIDATE_AMBIGUOUS = "candidate-ambiguous"
    CANDIDATE_DISPLAY_GUARD_MISMATCH = "candidate-display-guard-mismatch"
    OWNER_EVIDENCE_MALFORMED = "owner-evidence-malformed"


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
    manifest_id: str
    inventory_id: str
    ordinal: int
    origin: CourseReferenceSelectionOrigin
    role: CourseReferenceRole
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
        _content_id(self.manifest_id, field="manifest_id")
        _content_id(self.inventory_id, field="inventory_id")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= _MAX_ITEMS:
            raise CourseReferenceAuthorityError(
                "selection ordinal is outside the supported range"
            )
        if not isinstance(self.origin, CourseReferenceSelectionOrigin):
            raise TypeError("origin must be CourseReferenceSelectionOrigin")
        if self.role is not CourseReferenceRole.MANUSCRIPT_BIBLIOGRAPHY:
            raise CourseReferenceAuthorityError(
                "selection role must be manuscript-bibliography"
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
class CourseReferenceResolutionScopeEvidence(DataObjectModel):
    """Mirror the complete Courses 1.0 resolution-scope envelope."""

    scope_id: str
    course_id: str
    course_title: str
    manifest_id: str
    manifest_sha256: str
    inventory_id: str
    total: int
    ordered_selection_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _content_id(self.scope_id, field="scope_id")
        _bounded(self.course_id, field="course_id")
        _bounded(self.course_title, field="course_title", maximum=500)
        _content_id(self.manifest_id, field="manifest_id")
        _sha256(self.manifest_sha256, field="manifest_sha256")
        _content_id(self.inventory_id, field="inventory_id")
        if (
            type(self.total) is not int
            or not 1 <= self.total <= _MAX_ITEMS
            or self.total != len(self.ordered_selection_ids)
        ):
            raise CourseReferenceAuthorityError(
                "scope total differs from its ordered selection inventory"
            )
        _content_ids(
            self.ordered_selection_ids,
            field="ordered_selection_ids",
            ordered=True,
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
class RenderedEntryCandidateBinding(DataObjectModel):
    """Bind an opaque rendered locator to one exact candidate identity."""

    reference_locator: str
    rendered_entry_id: str
    candidate_id: str
    source_observation_ids: tuple[str, ...]
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        _content_id(self.reference_locator, field="reference_locator")
        _content_id(self.rendered_entry_id, field="rendered_entry_id")
        _content_id(self.candidate_id, field="candidate_id")
        _content_ids(
            self.source_observation_ids,
            field="source_observation_ids",
        )
        if self.reference_locator != self.rendered_entry_id:
            raise CourseReferenceAuthorityError(
                "rendered candidate locator differs from its entry identity"
            )
        object.__setattr__(
            self,
            "binding_id",
            _stable_id(
                "rendered-entry-candidate-binding",
                {
                    "candidate_id": self.candidate_id,
                    "reference_locator": self.reference_locator,
                    "rendered_entry_id": self.rendered_entry_id,
                    "source_observation_ids": self.source_observation_ids,
                },
            ),
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
class IngestionArtifactAuthorityLink(DataObjectModel):
    """Bind one asset observation to exact Ingestion cross-binding fields."""

    asset_observation_id: str
    source_id: str
    document_id: str
    artifact_verification_result_id: str
    link_id: str = field(init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("asset_observation_id", self.asset_observation_id),
            ("source_id", self.source_id),
            ("document_id", self.document_id),
            (
                "artifact_verification_result_id",
                self.artifact_verification_result_id,
            ),
        ):
            _content_id(value, field=label)
        object.__setattr__(
            self,
            "link_id",
            _stable_id(
                "reference-ingestion-artifact-link",
                {
                    "artifact_verification_result_id": (
                        self.artifact_verification_result_id
                    ),
                    "asset_observation_id": self.asset_observation_id,
                    "document_id": self.document_id,
                    "source_id": self.source_id,
                },
            ),
        )


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
    ingestion_artifact_links: tuple[IngestionArtifactAuthorityLink, ...] = ()

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
        _typed_tuple(
            self.ingestion_artifact_links,
            IngestionArtifactAuthorityLink,
            field="ingestion_artifact_links",
        )
        if any(
            item.asset_observation_id != self.asset_observation_id
            for item in self.ingestion_artifact_links
        ):
            raise CourseReferenceAuthorityError(
                "Ingestion artifact link differs from its asset observation"
            )
        if tuple(
            item.link_id for item in self.ingestion_artifact_links
        ) != tuple(
            sorted({item.link_id for item in self.ingestion_artifact_links})
        ):
            raise CourseReferenceAuthorityError(
                "Ingestion artifact links must use unique lexical order"
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
        ingestion_artifact_links: tuple[
            IngestionArtifactAuthorityLink, ...
        ] = (),
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
            ingestion_artifact_links=tuple(
                sorted(
                    ingestion_artifact_links,
                    key=lambda item: item.link_id,
                )
            ),
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

    scope: CourseReferenceResolutionScopeEvidence
    selections: tuple[CourseReferenceSelectionEvidence, ...]
    render_result: CandidateBibliographyRenderResult
    candidates: tuple[ReferenceCandidate, ...]
    rendered_candidate_bindings: tuple[RenderedEntryCandidateBinding, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    review_projection: ReviewProjection
    state_projections: tuple[ReferenceStateProjection, ...]
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError(
                "scope must be CourseReferenceResolutionScopeEvidence"
            )
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
        )
        _typed_tuple(
            self.rendered_candidate_bindings,
            RenderedEntryCandidateBinding,
            field="rendered_candidate_bindings",
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
            ("rendered candidate bindings", self.rendered_candidate_bindings),
            ("record discrepancies", self.record_discrepancies),
            ("assets", self.assets),
            ("state projections", self.state_projections),
        ):
            if len(values) > _MAX_ITEMS:
                raise CourseReferenceAuthorityError(f"{label} limit exceeded")
        if tuple(item.selection_id for item in self.selections) != (
            self.scope.ordered_selection_ids
        ):
            raise CourseReferenceAuthorityError(
                "selections differ from the complete Courses scope envelope"
            )
        if len(self.selections) != self.scope.total:
            raise CourseReferenceAuthorityError(
                "selection count differs from Courses scope total"
            )
        if any(
            item.scope_id != self.scope.scope_id
            or item.course_id != self.scope.course_id
            or item.manifest_id != self.scope.manifest_id
            or item.inventory_id != self.scope.inventory_id
            for item in self.selections
        ):
            raise CourseReferenceAuthorityError(
                "selections differ from the Courses scope revision"
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
            (
                item.reference_locator
                for item in self.rendered_candidate_bindings
            ),
            field="rendered candidate locators",
        )
        _unique(
            (item.binding_id for item in self.rendered_candidate_bindings),
            field="rendered candidate binding identities",
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
                    "asset_evidence": tuple(
                        sorted(
                            (
                                item.asset_observation_id,
                                item,
                            )
                            for item in self.assets
                        )
                    ),
                    "asset_observation_ids": tuple(
                        sorted(
                            item.asset_observation_id for item in self.assets
                        )
                    ),
                    "candidate_evidence": tuple(
                        sorted(
                            self.candidates,
                            key=lambda item: item.candidate_id,
                        )
                    ),
                    "candidate_ids": tuple(
                        sorted(item.candidate_id for item in self.candidates)
                    ),
                    "contract_id": COURSE_REFERENCE_AUTHORITY_CONTRACT_ID,
                    "observation_evidence": tuple(
                        sorted(
                            (
                                ObservedCandidateEntry.from_observation(item)
                                for source in (
                                    self.render_result.request.source.sources
                                )
                                for item in source.observations
                            ),
                            key=lambda item: item.observation_id,
                        )
                    ),
                    "record_evidence": tuple(
                        sorted(
                            self.record_discrepancies,
                            key=lambda item: item.record_id,
                        )
                    ),
                    "record_ids": tuple(
                        sorted(
                            item.record_id for item in self.record_discrepancies
                        )
                    ),
                    "render_result_id": self.render_result.result_id,
                    "rendered_entries": tuple(
                        RenderedCandidateEntryEvidence.from_rendered(item)
                        for item in self.render_result.entries
                    ),
                    "rendered_candidate_binding_evidence": tuple(
                        sorted(
                            self.rendered_candidate_bindings,
                            key=lambda item: item.binding_id,
                        )
                    ),
                    "rendered_candidate_binding_ids": tuple(
                        sorted(
                            item.binding_id
                            for item in self.rendered_candidate_bindings
                        )
                    ),
                    "review_projection": self.review_projection,
                    "review_projection_id": (
                        self.review_projection.projection_id
                    ),
                    "scope": self.scope,
                    "scope_id": self.scope.scope_id,
                    "selections": self.selections,
                    "selection_ids": tuple(
                        item.selection_id for item in self.selections
                    ),
                    "state_projection_evidence": tuple(
                        sorted(
                            self.state_projections,
                            key=lambda item: item.projection_id,
                        )
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
    resolution: CourseReferenceItemResolution
    candidate: ReferenceCandidate | None
    observations: tuple[ObservedCandidateEntry, ...]
    rendered_entry: RenderedCandidateEntryEvidence | None
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
        if not isinstance(self.resolution, CourseReferenceItemResolution):
            raise TypeError("resolution has an invalid type")
        if (
            self.candidate is not None
            and type(self.candidate) is not ReferenceCandidate
        ):
            raise TypeError("candidate has an invalid type")
        _typed_tuple(
            self.observations,
            ObservedCandidateEntry,
            field="observations",
        )
        if (
            self.rendered_entry is not None
            and type(self.rendered_entry) is not RenderedCandidateEntryEvidence
        ):
            raise TypeError("rendered_entry has an invalid type")
        ready = self.resolution is CourseReferenceItemResolution.READY
        if ready and (
            self.candidate is None
            or self.rendered_entry is None
            or not self.observations
        ):
            raise CourseReferenceAuthorityError(
                "ready item lacks complete candidate evidence"
            )
        if not ready and (
            self.allowed_identity_actions or self.allowed_asset_actions
        ):
            raise CourseReferenceAuthorityError(
                "unresolved item cannot expose mutation actions"
            )
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
                    "asset_evidence": self.assets,
                    "asset_observation_ids": tuple(
                        item.asset_observation_id for item in self.assets
                    ),
                    "candidate_id": (
                        None
                        if self.candidate is None
                        else self.candidate.candidate_id
                    ),
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
                    "rendered_entry_id": (
                        None
                        if self.rendered_entry is None
                        else self.rendered_entry.entry_id
                    ),
                    "resolution": self.resolution,
                    "selection_id": self.selection.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityQueue(DataObjectModel):
    """Deterministic complete queue for one Courses-owned selection scope."""

    request_id: str
    scope: CourseReferenceResolutionScopeEvidence
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
        if type(self.scope) is not CourseReferenceResolutionScopeEvidence:
            raise TypeError("scope has an invalid type")
        for label, value in (
            ("request_id", self.request_id),
            ("scope_id", self.scope_id),
            ("source_export_result_id", self.source_export_result_id),
            ("render_result_id", self.render_result_id),
            ("review_projection_id", self.review_projection_id),
        ):
            _content_id(value, field=label)
        _bounded(self.course_id, field="course_id")
        if (
            self.scope.scope_id != self.scope_id
            or self.scope.course_id != self.course_id
            or tuple(item.selection.selection_id for item in self.items)
            != self.scope.ordered_selection_ids
        ):
            raise CourseReferenceAuthorityError(
                "queue differs from its complete Courses scope envelope"
            )
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
                    "scope": self.scope,
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


def _unresolved_item(
    selection: CourseReferenceSelectionEvidence,
    resolution: CourseReferenceItemResolution,
    *,
    rendered: RenderedCandidateEntryEvidence | None = None,
    candidate: ReferenceCandidate | None = None,
) -> CourseReferenceAuthorityQueueItem:
    return CourseReferenceAuthorityQueueItem(
        selection=selection,
        resolution=resolution,
        candidate=candidate,
        observations=(),
        rendered_entry=rendered,
        record_matches=(),
        assets=(),
        current_identity_decisions=(),
        current_asset_decision=None,
        active_authority=None,
        allowed_identity_actions=(),
        allowed_asset_actions=(),
    )


def _validate_queue_request_freshness(
    request: CourseReferenceAuthorityQueueRequest,
) -> None:
    scope = CourseReferenceResolutionScopeEvidence(
        scope_id=request.scope.scope_id,
        course_id=request.scope.course_id,
        course_title=request.scope.course_title,
        manifest_id=request.scope.manifest_id,
        manifest_sha256=request.scope.manifest_sha256,
        inventory_id=request.scope.inventory_id,
        total=request.scope.total,
        ordered_selection_ids=request.scope.ordered_selection_ids,
    )
    selections = tuple(
        CourseReferenceSelectionEvidence(
            scope_id=item.scope_id,
            selection_id=item.selection_id,
            locator_binding_id=item.locator_binding_id,
            course_id=item.course_id,
            manifest_id=item.manifest_id,
            inventory_id=item.inventory_id,
            ordinal=item.ordinal,
            origin=item.origin,
            role=item.role,
            display_citekey=item.display_citekey,
            display_citekey_status=item.display_citekey_status,
            reference_locator=item.reference_locator,
        )
        for item in request.selections
    )
    fresh = CourseReferenceAuthorityQueueRequest(
        scope=scope,
        selections=selections,
        render_result=request.render_result,
        candidates=request.candidates,
        rendered_candidate_bindings=request.rendered_candidate_bindings,
        record_discrepancies=request.record_discrepancies,
        assets=request.assets,
        review_projection=request.review_projection,
        state_projections=request.state_projections,
    )
    if fresh.request_id != request.request_id:
        raise CourseReferenceAuthorityError(
            "course authority queue request revision is stale"
        )


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
        _validate_queue_request_freshness(request)
        rendered_by_id = {
            item.entry_id: item for item in request.render_result.entries
        }
        candidates_by_id = {
            item.candidate_id: item for item in request.candidates
        }
        bindings_by_locator = {
            item.reference_locator: item
            for item in request.rendered_candidate_bindings
        }
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
        items: list[CourseReferenceAuthorityQueueItem] = []
        for selection in request.selections:
            rendered = rendered_by_id.get(selection.reference_locator)
            if rendered is None:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.RENDERED_LOCATOR_UNAVAILABLE,
                    )
                )
                continue
            rendered_evidence = RenderedCandidateEntryEvidence.from_rendered(
                rendered
            )
            if rendered.citekey != selection.display_citekey:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.DISPLAY_GUARD_MISMATCH,
                        rendered=rendered_evidence,
                    )
                )
                continue
            binding = bindings_by_locator.get(selection.reference_locator)
            if binding is None:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.CANDIDATE_UNAVAILABLE,
                        rendered=rendered_evidence,
                    )
                )
                continue
            candidate = candidates_by_id.get(binding.candidate_id)
            if candidate is None:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.CANDIDATE_UNAVAILABLE,
                        rendered=rendered_evidence,
                    )
                )
                continue
            if (
                binding.rendered_entry_id != rendered.entry_id
                or binding.source_observation_ids
                != rendered.source_observation_ids
                or binding.source_observation_ids
                != candidate.source_observation_ids
            ):
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.OWNER_EVIDENCE_MALFORMED,
                        rendered=rendered_evidence,
                    )
                )
                continue
            if candidate.proposed_citekey != rendered.citekey:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.CANDIDATE_DISPLAY_GUARD_MISMATCH,
                        rendered=rendered_evidence,
                        candidate=candidate,
                    )
                )
                continue
            try:
                source_observations = tuple(
                    observations[item]
                    for item in rendered.source_observation_ids
                )
            except KeyError:
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.OWNER_EVIDENCE_MALFORMED,
                        rendered=rendered_evidence,
                    )
                )
                continue
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
                items.append(
                    _unresolved_item(
                        selection,
                        CourseReferenceItemResolution.OWNER_EVIDENCE_MALFORMED,
                        rendered=rendered_evidence,
                    )
                )
                continue
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
                    resolution=CourseReferenceItemResolution.READY,
                    candidate=candidate,
                    observations=observed,
                    rendered_entry=rendered_evidence,
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
        return CourseReferenceAuthorityQueue(
            request_id=request.request_id,
            scope=request.scope,
            scope_id=request.scope.scope_id,
            course_id=request.scope.course_id,
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
class ReferenceIdentityDecisionPreview(DataObjectModel):
    """Owner-generated explicit identity action preview."""

    queue: CourseReferenceAuthorityQueue
    selection_id: str
    disposition: ReferenceIdentityDecision
    target_state_projection_id: str | None
    canonical_citekey: str | None
    alias_citekeys: tuple[str, ...]
    selected_record_match_ids: tuple[str, ...]
    expected_current_decision_id: str | None
    preview_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.queue) is not CourseReferenceAuthorityQueue:
            raise TypeError("queue has an invalid type")
        item = self.queue.item(self.selection_id)
        candidate = _ready_candidate(item)
        if self.disposition not in item.allowed_identity_actions:
            raise CourseReferenceAuthorityError(
                "identity disposition is not currently allowed"
            )
        _citekeys(self.alias_citekeys, field="alias_citekeys")
        _content_ids(
            self.selected_record_match_ids,
            field="selected_record_match_ids",
        )
        available_match_ids = {match.record_id for match in item.record_matches}
        if not set(self.selected_record_match_ids).issubset(
            available_match_ids
        ):
            raise CourseReferenceAuthorityError(
                "identity preview selects an unavailable record match"
            )
        accepting = self.disposition in {
            ReferenceIdentityDecision.ACCEPT_NEW,
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }
        if accepting != (self.canonical_citekey is not None):
            raise CourseReferenceAuthorityError(
                "canonical citekey does not match identity disposition"
            )
        if self.canonical_citekey is not None:
            validate_citekey(
                self.canonical_citekey,
                field="canonical citekey",
            )
            if self.canonical_citekey in self.alias_citekeys:
                raise CourseReferenceAuthorityError(
                    "canonical citekey cannot also be an alias"
                )
        needs_target = self.disposition in {
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }
        if needs_target != (self.target_state_projection_id is not None):
            raise CourseReferenceAuthorityError(
                "identity target does not match the disposition"
            )
        target = (
            None
            if self.target_state_projection_id is None
            else _target_authority(
                self.queue,
                self.target_state_projection_id,
            )
        )
        if self.disposition is ReferenceIdentityDecision.ACCEPT_NEW:
            if self.canonical_citekey != candidate.proposed_citekey:
                raise CourseReferenceAuthorityError(
                    "new work canonical citekey must be explicitly confirmed"
                )
            if self.alias_citekeys:
                raise CourseReferenceAuthorityError(
                    "new work cannot begin with inferred aliases"
                )
            if any(
                authority.active_citekey == self.canonical_citekey
                for authority in self.queue.active_authorities
            ):
                raise CourseReferenceAuthorityError(
                    "canonical citekey is already active"
                )
        elif target is not None:
            if (
                self.disposition is ReferenceIdentityDecision.ACCEPT_EXISTING
                and candidate.proposed_citekey != target.active_citekey
            ):
                raise CourseReferenceAuthorityError(
                    "existing-work target differs from the candidate key"
                )
            if self.canonical_citekey != target.active_citekey:
                raise CourseReferenceAuthorityError(
                    "canonical citekey differs from the explicit target"
                )
            expected_aliases = set(target.alias_citekeys)
            if (
                self.disposition is ReferenceIdentityDecision.MERGE
                and candidate.proposed_citekey != target.active_citekey
            ):
                expected_aliases.add(candidate.proposed_citekey)
            if self.alias_citekeys != tuple(sorted(expected_aliases)):
                raise CourseReferenceAuthorityError(
                    "explicit aliases differ from the target/merge plan"
                )
        elif self.alias_citekeys:
            raise CourseReferenceAuthorityError(
                "non-accepting identity preview cannot carry aliases"
            )
        context_id = (
            item.selection.course_id
            if self.disposition is ReferenceIdentityDecision.DEFER
            else _IDENTITY_CONTEXT
        )
        current = _current_decision(
            item.current_identity_decisions,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            context_id=context_id,
        )
        _require_expected_head(current, self.expected_current_decision_id)
        object.__setattr__(
            self,
            "preview_id",
            _stable_id(
                "reference-identity-decision-preview",
                {
                    "alias_citekeys": self.alias_citekeys,
                    "canonical_citekey": self.canonical_citekey,
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "item_revision_id": item.item_revision_id,
                    "queue_id": self.queue.queue_id,
                    "selected_record_match_ids": (
                        self.selected_record_match_ids
                    ),
                    "selection_id": self.selection_id,
                    "target_state_projection_id": (
                        self.target_state_projection_id
                    ),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetEvidencePlan(DataObjectModel):
    """Fresh post-identity plan binding all asset competitors and evidence."""

    queue: CourseReferenceAuthorityQueue
    selection_id: str
    identity_state_projection_id: str
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        item = self.queue.item(self.selection_id)
        _ready_candidate(item)
        if item.active_authority is None:
            raise CourseReferenceAuthorityError(
                "asset plan requires current accepted identity"
            )
        if (
            self.identity_state_projection_id
            != item.active_authority.state_projection_id
        ):
            raise CourseReferenceAuthorityError(
                "asset plan identity projection is stale"
            )
        if self.assets != item.assets:
            raise CourseReferenceAuthorityError(
                "asset plan differs from the refreshed queue evidence"
            )
        _typed_tuple(
            self.assets,
            ReferenceAssetAuthorityEvidence,
            field="assets",
        )
        object.__setattr__(
            self,
            "plan_id",
            _stable_id(
                "canonical-asset-evidence-plan",
                {
                    "asset_evidence": self.assets,
                    "identity_state_projection_id": (
                        self.identity_state_projection_id
                    ),
                    "item_revision_id": item.item_revision_id,
                    "queue_id": self.queue.queue_id,
                    "selection_id": self.selection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetCompetitorDisposition(DataObjectModel):
    """Record an explicit action and rationale for one plan competitor."""

    asset_observation_id: str
    disposition: CanonicalAssetDecision
    rationale: str

    def __post_init__(self) -> None:
        _content_id(
            self.asset_observation_id,
            field="asset_observation_id",
        )
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("competitor disposition is invalid")
        _bounded(self.rationale, field="competitor rationale")


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalAssetDecisionPreview(DataObjectModel):
    """Owner-generated asset decision preview over a complete fresh plan."""

    plan: CanonicalAssetEvidencePlan
    disposition: CanonicalAssetDecision
    competitor_dispositions: tuple[CanonicalAssetCompetitorDisposition, ...]
    expected_current_decision_id: str | None
    preview_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.plan) is not CanonicalAssetEvidencePlan:
            raise TypeError("plan has an invalid type")
        if not isinstance(self.disposition, CanonicalAssetDecision):
            raise TypeError("asset disposition is invalid")
        _typed_tuple(
            self.competitor_dispositions,
            CanonicalAssetCompetitorDisposition,
            field="competitor_dispositions",
        )
        asset_ids = tuple(
            item.asset_observation_id for item in self.plan.assets
        )
        disposition_ids = tuple(
            item.asset_observation_id for item in self.competitor_dispositions
        )
        if tuple(sorted(asset_ids)) != tuple(sorted(disposition_ids)):
            raise CourseReferenceAuthorityError(
                "asset preview must disposition every competitor exactly once"
            )
        selected = tuple(
            item
            for item in self.competitor_dispositions
            if item.disposition is CanonicalAssetDecision.AUTHORIZE
        )
        if self.disposition is CanonicalAssetDecision.AUTHORIZE:
            if len(selected) != 1:
                raise CourseReferenceAuthorityError(
                    "asset authorization must select exactly one competitor"
                )
            selected_asset = _asset(
                self.plan.queue.item(self.plan.selection_id),
                selected[0].asset_observation_id,
            )
            if selected_asset.runtime_availability is not (
                RuntimeAssetAvailability.AVAILABLE
            ):
                raise CourseReferenceAuthorityError(
                    "authorized asset is not freshly available"
                )
        elif selected:
            raise CourseReferenceAuthorityError(
                "non-authorization preview cannot authorize a competitor"
            )
        item = self.plan.queue.item(self.plan.selection_id)
        _require_expected_head(
            item.current_asset_decision,
            self.expected_current_decision_id,
        )
        object.__setattr__(
            self,
            "preview_id",
            _stable_id(
                "canonical-asset-decision-preview",
                {
                    "competitor_dispositions": (self.competitor_dispositions),
                    "disposition": self.disposition,
                    "expected_current_decision_id": (
                        self.expected_current_decision_id
                    ),
                    "plan_id": self.plan.plan_id,
                },
            ),
        )

    @property
    def selected_asset_observation_id(self) -> str | None:
        for item in self.competitor_dispositions:
            if item.disposition is CanonicalAssetDecision.AUTHORIZE:
                return item.asset_observation_id
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendReferenceIdentityDecisionRequest(DataObjectActionRequest):
    """Append exactly one owner-generated identity preview."""

    preview: ReferenceIdentityDecisionPreview
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.preview) is not ReferenceIdentityDecisionPreview:
            raise TypeError("preview has an invalid type")
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor must be ReviewActorProvenance")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "append-reference-identity-decision-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "preview_id": self.preview.preview_id,
                    "rationale": self.rationale,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendCanonicalAssetDecisionRequest(DataObjectActionRequest):
    """Append exactly one owner-generated complete asset preview."""

    preview: CanonicalAssetDecisionPreview
    actor: ReviewActorProvenance
    rationale: str
    decided_at: str
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.preview) is not CanonicalAssetDecisionPreview:
            raise TypeError("preview has an invalid type")
        if type(self.actor) is not ReviewActorProvenance:
            raise TypeError("actor must be ReviewActorProvenance")
        _bounded(self.rationale, field="rationale")
        _bounded(self.decided_at, field="decided_at")
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "append-canonical-asset-decision-request",
                {
                    "actor": self.actor,
                    "decided_at": self.decided_at,
                    "preview_id": self.preview.preview_id,
                    "rationale": self.rationale,
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
        expected_preview_id: str,
        expected_asset_plan_id: str | None,
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
        """Append exactly one fresh explicit identity preview."""
        if type(request) is not AppendReferenceIdentityDecisionRequest:
            raise TypeError("request has an invalid identity request type")
        preview = request.preview
        queue = preview.queue
        item = queue.item(preview.selection_id)
        candidate = self._candidate(_ready_candidate(item).candidate_id)
        assert item.rendered_entry is not None
        context = (
            item.selection.course_id
            if preview.disposition is ReferenceIdentityDecision.DEFER
            else _IDENTITY_CONTEXT
        )
        current = _current_decision(
            item.current_identity_decisions,
            dimension=HumanReviewDimension.REFERENCE_IDENTITY,
            context_id=context,
        )
        _require_expected_head(current, preview.expected_current_decision_id)
        target = (
            None
            if preview.target_state_projection_id is None
            else _target_authority(
                queue,
                preview.target_state_projection_id,
            )
        )
        evidence_ids = {
            queue.queue_id,
            queue.review_projection_id,
            preview.preview_id,
            item.item_revision_id,
            item.selection.scope_id,
            item.selection.selection_id,
            item.selection.locator_binding_id,
            item.rendered_entry.entry_id,
            candidate.candidate_id,
            request.actor.verification_record_id,
            *(entry.observation_id for entry in item.observations),
            *preview.selected_record_match_ids,
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
            decision=preview.disposition,
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
        if preview.disposition in {
            ReferenceIdentityDecision.ACCEPT_NEW,
            ReferenceIdentityDecision.ACCEPT_EXISTING,
            ReferenceIdentityDecision.MERGE,
        }:
            assert preview.canonical_citekey is not None
            state_projection = _identity_state_projection(
                candidate=candidate,
                decision=decision,
                disposition=preview.disposition,
                target=target,
                canonical_citekey=preview.canonical_citekey,
                alias_citekeys=preview.alias_citekeys,
            )
        self._repository.append_course_authority_decision(
            candidate=candidate,
            observations=self._candidate_observations(candidate),
            decision=decision,
            state_projection=state_projection,
            expected_current_decision_id=preview.expected_current_decision_id,
            expected_queue_id=queue.queue_id,
            expected_item_revision_id=item.item_revision_id,
            expected_preview_id=preview.preview_id,
            expected_asset_plan_id=None,
            expected_review_projection_id=queue.review_projection_id,
            expected_state_projection_ids=queue.state_projection_ids,
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
        """Append exactly one fresh complete asset preview."""
        if type(request) is not AppendCanonicalAssetDecisionRequest:
            raise TypeError("request has an invalid asset request type")
        preview = request.preview
        plan = preview.plan
        queue = plan.queue
        item = queue.item(plan.selection_id)
        candidate = self._candidate(_ready_candidate(item).candidate_id)
        if item.active_authority is None:
            raise CourseReferenceAuthorityError(
                "asset decision requires accepted identity authority"
            )
        current = item.current_asset_decision
        _require_expected_head(current, preview.expected_current_decision_id)
        selected = (
            None
            if preview.selected_asset_observation_id is None
            else _asset(item, preview.selected_asset_observation_id)
        )
        evidence_ids = {
            queue.queue_id,
            queue.review_projection_id,
            plan.plan_id,
            preview.preview_id,
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
            evidence_ids.update(_asset_evidence_ids(selected))
        decision = HumanReviewDecision.create(
            subject_id=candidate.candidate_id,
            context_id=_ASSET_CONTEXT,
            dimension=HumanReviewDimension.CANONICAL_ASSET,
            decision=preview.disposition,
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
        if preview.disposition is CanonicalAssetDecision.AUTHORIZE:
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
            expected_current_decision_id=preview.expected_current_decision_id,
            expected_queue_id=queue.queue_id,
            expected_item_revision_id=item.item_revision_id,
            expected_preview_id=preview.preview_id,
            expected_asset_plan_id=plan.plan_id,
            expected_review_projection_id=queue.review_projection_id,
            expected_state_projection_ids=queue.state_projection_ids,
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


class CourseReferenceAuthorityFailureReason(StrEnum):
    """Stable API-mappable owner service failure categories."""

    COURSE_NOT_FOUND = "course-not-found"
    ITEM_NOT_FOUND = "item-not-found"
    EVIDENCE_STALE = "evidence-stale"
    REVISION_STALE = "revision-stale"
    TARGET_STALE = "target-stale"
    CONCURRENT_DECISION = "concurrent-decision"
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
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseReferenceAuthorityOwnerEvidence(DataObjectModel):
    """Owner-private evidence loaded behind the runtime façade."""

    render_result: CandidateBibliographyRenderResult
    candidates: tuple[ReferenceCandidate, ...]
    observations: tuple[SourceBibliographyObservation, ...]
    rendered_candidate_bindings: tuple[RenderedEntryCandidateBinding, ...]
    record_discrepancies: tuple[ReferenceRecordDiscrepancy, ...]
    assets: tuple[ReferenceAssetAuthorityEvidence, ...]
    evidence_revision_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.render_result) is not CandidateBibliographyRenderResult:
            raise TypeError("render_result has an invalid type")
        _typed_tuple(
            self.candidates,
            ReferenceCandidate,
            field="candidates",
        )
        _typed_tuple(
            self.observations,
            SourceBibliographyObservation,
            field="observations",
        )
        _typed_tuple(
            self.rendered_candidate_bindings,
            RenderedEntryCandidateBinding,
            field="rendered_candidate_bindings",
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


class CourseReferenceAuthorityEvidenceProvider(Protocol):
    """Load owner-private artifacts and runtime evidence behind References."""

    def load_course_reference_authority_evidence(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        catalog_candidates: tuple[ReferenceCandidate, ...],
        catalog_observations: tuple[SourceBibliographyObservation, ...],
        catalog_assets: tuple[SourceAssetRecord, ...],
    ) -> CourseReferenceAuthorityOwnerEvidence: ...


class CourseReferenceAuthorityRuntimeCatalog(
    CourseReferenceAuthorityRepository,
    Protocol,
):
    """Schema-5 reads and atomic append required by the runtime service."""

    def read_candidates(self) -> tuple[ReferenceCandidate, ...]: ...

    def read_observations(
        self,
    ) -> tuple[SourceBibliographyObservation, ...]: ...

    def read_source_assets(self) -> tuple[SourceAssetRecord, ...]: ...

    def read_review_projection(self) -> ReviewProjection: ...

    def read_state_projections(
        self,
    ) -> tuple[ReferenceStateProjection, ...]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAuthorityDecisionReceipt(DataObjectModel):
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
            or self.refreshed_queue.item(
                self.refreshed_item.selection.selection_id
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


class CourseReferenceAuthorityService:
    """Only API-facing owner façade for queue, preview, append, and reread."""

    __slots__ = ("_catalog", "_provider")

    def __init__(
        self,
        *,
        catalog: CourseReferenceAuthorityRuntimeCatalog,
        provider: CourseReferenceAuthorityEvidenceProvider,
    ) -> None:
        self._catalog = catalog
        self._provider = provider

    def queue(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        selections: tuple[CourseReferenceSelectionEvidence, ...],
    ) -> CourseReferenceAuthorityQueue:
        queue, _ = self._load(scope=scope, selections=selections)
        return queue

    def preview_identity(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        selections: tuple[CourseReferenceSelectionEvidence, ...],
        selection_id: str,
        disposition: ReferenceIdentityDecision,
        target_state_projection_id: str | None,
        canonical_citekey: str | None,
        alias_citekeys: tuple[str, ...],
        selected_record_match_ids: tuple[str, ...],
        expected_current_decision_id: str | None,
    ) -> ReferenceIdentityDecisionPreview:
        queue = self.queue(scope=scope, selections=selections)
        try:
            queue.item(selection_id)
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.ITEM_NOT_FOUND,
                "course reference item is unavailable",
            ) from error
        try:
            return ReferenceIdentityDecisionPreview(
                queue=queue,
                selection_id=selection_id,
                disposition=disposition,
                target_state_projection_id=target_state_projection_id,
                canonical_citekey=canonical_citekey,
                alias_citekeys=alias_citekeys,
                selected_record_match_ids=selected_record_match_ids,
                expected_current_decision_id=expected_current_decision_id,
            )
        except CourseReferenceAuthorityError as error:
            reason = (
                CourseReferenceAuthorityFailureReason.TARGET_STALE
                if target_state_projection_id is not None
                else CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION
            )
            raise CourseReferenceAuthorityServiceError(
                reason,
                "identity preview is not available",
            ) from error

    def preview_asset(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        selections: tuple[CourseReferenceSelectionEvidence, ...],
        selection_id: str,
        disposition: CanonicalAssetDecision,
        competitor_dispositions: tuple[
            CanonicalAssetCompetitorDisposition, ...
        ],
        expected_current_decision_id: str | None,
    ) -> CanonicalAssetDecisionPreview:
        queue = self.queue(scope=scope, selections=selections)
        try:
            item = queue.item(selection_id)
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.ITEM_NOT_FOUND,
                "course reference item is unavailable",
            ) from error
        try:
            if item.active_authority is None:
                raise CourseReferenceAuthorityError(
                    "asset preview lacks accepted identity"
                )
            plan = CanonicalAssetEvidencePlan(
                queue=queue,
                selection_id=selection_id,
                identity_state_projection_id=(
                    item.active_authority.state_projection_id
                ),
                assets=item.assets,
            )
            return CanonicalAssetDecisionPreview(
                plan=plan,
                disposition=disposition,
                competitor_dispositions=competitor_dispositions,
                expected_current_decision_id=(expected_current_decision_id),
            )
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.INVALID_DISPOSITION,
                "asset preview is not available",
            ) from error

    def append_identity(
        self,
        *,
        preview: ReferenceIdentityDecisionPreview,
        actor: ReviewActorProvenance,
        rationale: str,
        decided_at: str,
    ) -> ReferenceAuthorityDecisionReceipt:
        selections = tuple(item.selection for item in preview.queue.items)
        fresh_queue, evidence = self._load(
            scope=preview.queue.scope,
            selections=selections,
        )
        old_candidate = _ready_candidate(
            preview.queue.item(preview.selection_id)
        )
        decision_history = (
            self._catalog.read_review_projection().human_decision_history
        )
        retry = any(
            item.subject_id == old_candidate.candidate_id
            and item.dimension is HumanReviewDimension.REFERENCE_IDENTITY
            and item.decision == preview.disposition.value
            and item.actor == actor
            and item.rationale == rationale
            and item.decided_at == decided_at
            and preview.preview_id in item.evidence_ids
            for item in decision_history
        )
        if retry:
            appender = ReferenceAuthorityDecisionAppender(
                repository=self._catalog,
                candidates=evidence.candidates,
                observations=evidence.observations,
            )
            result = appender.append_identity(
                request=AppendReferenceIdentityDecisionRequest(
                    preview=preview,
                    actor=actor,
                    rationale=rationale,
                    decided_at=decided_at,
                )
            )
            return self._receipt(
                result=result,
                scope=preview.queue.scope,
                selections=selections,
                selection_id=preview.selection_id,
                preview_id=preview.preview_id,
            )
        try:
            fresh_preview = ReferenceIdentityDecisionPreview(
                queue=fresh_queue,
                selection_id=preview.selection_id,
                disposition=preview.disposition,
                target_state_projection_id=(preview.target_state_projection_id),
                canonical_citekey=preview.canonical_citekey,
                alias_citekeys=preview.alias_citekeys,
                selected_record_match_ids=(preview.selected_record_match_ids),
                expected_current_decision_id=(
                    preview.expected_current_decision_id
                ),
            )
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.REVISION_STALE,
                "identity preview revision is stale",
            ) from error
        if fresh_preview.preview_id != preview.preview_id:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
                "identity preview evidence is stale",
            )
        appender = ReferenceAuthorityDecisionAppender(
            repository=self._catalog,
            candidates=evidence.candidates,
            observations=evidence.observations,
        )
        try:
            result = appender.append_identity(
                request=AppendReferenceIdentityDecisionRequest(
                    preview=fresh_preview,
                    actor=actor,
                    rationale=rationale,
                    decided_at=decided_at,
                )
            )
        except Exception as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION,
                "identity decision append did not commit",
            ) from error
        return self._receipt(
            result=result,
            scope=preview.queue.scope,
            selections=tuple(item.selection for item in preview.queue.items),
            selection_id=preview.selection_id,
            preview_id=preview.preview_id,
        )

    def append_asset(
        self,
        *,
        preview: CanonicalAssetDecisionPreview,
        actor: ReviewActorProvenance,
        rationale: str,
        decided_at: str,
    ) -> ReferenceAuthorityDecisionReceipt:
        old_queue = preview.plan.queue
        selections = tuple(item.selection for item in old_queue.items)
        fresh_queue, evidence = self._load(
            scope=old_queue.scope,
            selections=selections,
        )
        old_candidate = _ready_candidate(
            old_queue.item(preview.plan.selection_id)
        )
        decision_history = (
            self._catalog.read_review_projection().human_decision_history
        )
        retry = any(
            item.subject_id == old_candidate.candidate_id
            and item.dimension is HumanReviewDimension.CANONICAL_ASSET
            and item.decision == preview.disposition.value
            and item.actor == actor
            and item.rationale == rationale
            and item.decided_at == decided_at
            and preview.preview_id in item.evidence_ids
            for item in decision_history
        )
        if retry:
            appender = ReferenceAuthorityDecisionAppender(
                repository=self._catalog,
                candidates=evidence.candidates,
                observations=evidence.observations,
            )
            result = appender.append_asset(
                request=AppendCanonicalAssetDecisionRequest(
                    preview=preview,
                    actor=actor,
                    rationale=rationale,
                    decided_at=decided_at,
                )
            )
            return self._receipt(
                result=result,
                scope=old_queue.scope,
                selections=selections,
                selection_id=preview.plan.selection_id,
                preview_id=preview.preview_id,
            )
        try:
            fresh_item = fresh_queue.item(preview.plan.selection_id)
            if fresh_item.active_authority is None:
                raise CourseReferenceAuthorityError(
                    "accepted identity is stale"
                )
            fresh_plan = CanonicalAssetEvidencePlan(
                queue=fresh_queue,
                selection_id=preview.plan.selection_id,
                identity_state_projection_id=(
                    fresh_item.active_authority.state_projection_id
                ),
                assets=fresh_item.assets,
            )
            fresh_preview = CanonicalAssetDecisionPreview(
                plan=fresh_plan,
                disposition=preview.disposition,
                competitor_dispositions=(preview.competitor_dispositions),
                expected_current_decision_id=(
                    preview.expected_current_decision_id
                ),
            )
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.REVISION_STALE,
                "asset plan revision is stale",
            ) from error
        if fresh_preview.preview_id != preview.preview_id:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.EVIDENCE_STALE,
                "asset runtime evidence is stale",
            )
        appender = ReferenceAuthorityDecisionAppender(
            repository=self._catalog,
            candidates=evidence.candidates,
            observations=evidence.observations,
        )
        try:
            result = appender.append_asset(
                request=AppendCanonicalAssetDecisionRequest(
                    preview=fresh_preview,
                    actor=actor,
                    rationale=rationale,
                    decided_at=decided_at,
                )
            )
        except Exception as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.CONCURRENT_DECISION,
                "asset decision append did not commit",
            ) from error
        return self._receipt(
            result=result,
            scope=old_queue.scope,
            selections=selections,
            selection_id=preview.plan.selection_id,
            preview_id=preview.preview_id,
        )

    def _load(
        self,
        *,
        scope: CourseReferenceResolutionScopeEvidence,
        selections: tuple[CourseReferenceSelectionEvidence, ...],
    ) -> tuple[
        CourseReferenceAuthorityQueue,
        CourseReferenceAuthorityOwnerEvidence,
    ]:
        try:
            evidence = self._provider.load_course_reference_authority_evidence(
                scope=scope,
                catalog_candidates=self._catalog.read_candidates(),
                catalog_observations=self._catalog.read_observations(),
                catalog_assets=self._catalog.read_source_assets(),
            )
            request = CourseReferenceAuthorityQueueRequest(
                scope=scope,
                selections=selections,
                render_result=evidence.render_result,
                candidates=evidence.candidates,
                rendered_candidate_bindings=(
                    evidence.rendered_candidate_bindings
                ),
                record_discrepancies=evidence.record_discrepancies,
                assets=evidence.assets,
                review_projection=self._catalog.read_review_projection(),
                state_projections=self._catalog.read_state_projections(),
            )
            queue = CourseReferenceAuthorityProjector().project(request=request)
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
        return queue, evidence

    def _receipt(
        self,
        *,
        result: ReferenceAuthorityDecisionResult,
        scope: CourseReferenceResolutionScopeEvidence,
        selections: tuple[CourseReferenceSelectionEvidence, ...],
        selection_id: str,
        preview_id: str,
    ) -> ReferenceAuthorityDecisionReceipt:
        queue = self.queue(scope=scope, selections=selections)
        try:
            item = queue.item(selection_id)
        except CourseReferenceAuthorityError as error:
            raise CourseReferenceAuthorityServiceError(
                CourseReferenceAuthorityFailureReason.ITEM_NOT_FOUND,
                "course reference item is unavailable after append",
            ) from error
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
        return ReferenceAuthorityDecisionReceipt(
            decision_result=result,
            preview_id=preview_id,
            refreshed_queue=queue,
            refreshed_item=item,
            refreshed_queue_id=queue.queue_id,
            refreshed_item_revision_id=item.item_revision_id,
            current_decision_id=result.decision.decision_id,
            current_state_projection_id=state_projection_id,
        )


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
    ingestion_artifact_links: tuple[IngestionArtifactAuthorityLink, ...]
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
        _typed_tuple(
            self.ingestion_artifact_links,
            IngestionArtifactAuthorityLink,
            field="ingestion_artifact_links",
            nonempty=True,
        )
        if tuple(
            item.link_id for item in self.ingestion_artifact_links
        ) != tuple(
            sorted({item.link_id for item in self.ingestion_artifact_links})
        ):
            raise CourseReferenceAuthorityError(
                "Search Ingestion links must use unique lexical order"
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
                    "ingestion_artifact_links": self.ingestion_artifact_links,
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
        candidate = _ready_candidate(item)
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
                candidate_id=candidate.candidate_id,
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
    asset_evidence: tuple[ReferenceAssetAuthorityEvidence, ...] = (),
) -> SearchReferenceAuthorityProjection:
    """Project only complete authority with typed Ingestion linkage."""
    active = _active_authorities(state_projections, review_projection)
    projections_by_id = {item.projection_id: item for item in state_projections}
    bindings = []
    for item in active:
        if (
            item.source_asset_id is None
            or item.canonical_asset_decision_id is None
            or item.authority_binding_id is None
        ):
            continue
        matching_assets = tuple(
            asset
            for asset in asset_evidence
            if asset.candidate_id == item.candidate_id
            and item.source_asset_id
            == _stable_id(
                "source-asset",
                {
                    "asset_observation_id": asset.asset_observation_id,
                    "authorization_decision_id": (
                        item.canonical_asset_decision_id
                    ),
                    "bibliographic_work_id": item.bibliographic_work_id,
                },
            )
        )
        if (
            len(matching_assets) != 1
            or not matching_assets[0].ingestion_artifact_links
        ):
            continue
        selected = matching_assets[0]
        authoritative_inputs = set(
            projections_by_id[item.state_projection_id].authoritative_input_ids
        )
        if (
            selected.runtime_availability
            is not RuntimeAssetAvailability.AVAILABLE
            or not set(_asset_evidence_ids(selected)).issubset(
                authoritative_inputs
            )
            or any(
                link.link_id not in authoritative_inputs
                for link in selected.ingestion_artifact_links
            )
        ):
            continue
        bindings.append(
            SearchReferenceAuthorityBinding(
                candidate_id=item.candidate_id,
                bibliographic_work_id=item.bibliographic_work_id,
                reference_identity_status="accepted",
                accepted_citekey=item.active_citekey,
                source_asset_id=item.source_asset_id,
                authority_binding_id=item.authority_binding_id,
                identity_decision_id=item.identity_decision_id,
                canonical_asset_decision_id=(item.canonical_asset_decision_id),
                ingestion_artifact_links=(selected.ingestion_artifact_links),
                authority_evidence_ids=projections_by_id[
                    item.state_projection_id
                ].authoritative_input_ids,
                state_projection_id=item.state_projection_id,
            )
        )
    return SearchReferenceAuthorityProjection(
        review_projection_id=review_projection.projection_id,
        bindings=tuple(sorted(bindings, key=lambda item: item.binding_id)),
    )


def _identity_state_projection(
    *,
    candidate: ReferenceCandidate,
    decision: HumanReviewDecision,
    disposition: ReferenceIdentityDecision,
    target: ActiveReferenceAuthority | None,
    canonical_citekey: str,
    alias_citekeys: tuple[str, ...],
) -> ReferenceStateProjection:
    if disposition is ReferenceIdentityDecision.ACCEPT_NEW:
        work_id = _stable_id(
            "bibliographic-work",
            {
                "candidate_id": candidate.candidate_id,
                "creating_decision_id": decision.decision_id,
            },
        )
        active_citekey = canonical_citekey
        aliases = alias_citekeys
    else:
        if target is None:
            raise CourseReferenceAuthorityError(
                "accepted existing or merged identity requires a target"
            )
        work_id = target.bibliographic_work_id
        active_citekey = canonical_citekey
        aliases = alias_citekeys
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


def _ready_candidate(
    item: CourseReferenceAuthorityQueueItem,
) -> ReferenceCandidate:
    if (
        item.resolution is not CourseReferenceItemResolution.READY
        or item.candidate is None
    ):
        raise CourseReferenceAuthorityError(
            "course reference item is unresolved and cannot mutate"
        )
    return item.candidate


def _asset_evidence_ids(
    asset: ReferenceAssetAuthorityEvidence,
) -> tuple[str, ...]:
    values = {
        asset.asset_observation_id,
        *asset.document_binding_ids,
        *asset.ingestion_evidence_ids,
        *(link.link_id for link in asset.ingestion_artifact_links),
    }
    if asset.runtime_evidence_id is not None:
        values.add(asset.runtime_evidence_id)
    return tuple(sorted(values))


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


def _content_ids(
    values: tuple[str, ...],
    *,
    field: str,
    ordered: bool = False,
) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    for value in values:
        _content_id(value, field=field)
    if len(values) != len(set(values)):
        raise CourseReferenceAuthorityError(f"{field} must be unique")
    if not ordered and values != tuple(sorted(values)):
        raise CourseReferenceAuthorityError(f"{field} must use lexical order")


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
