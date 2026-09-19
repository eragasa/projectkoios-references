from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Self, cast

from projectkoios.references.identity import ProducerIdentity
from projectkoios.references.io_limits import (
    REVIEW_IO_LIMITS,
    ReferenceIOLimits,
    validate_json_text_nesting,
)

_REVIEW_SCHEMA_VERSION = 1
_MAX_TEXT = 4096
_MAX_ITEMS = 256
_MAX_EVIDENCE_IDS = 64
_MAX_CONTENT_ID_BYTES = 512
_CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REFERENCE_DOMAIN = "projectkoios-references"
_REPLAY_PRODUCER = ProducerIdentity(
    "projectkoios.references.review-replay",
    "1",
)


class ReviewRecordError(ValueError):
    """Raised when review evidence or deterministic replay is invalid."""


class ReviewActorKind(StrEnum):
    PERSON = "person"
    PROCESSOR = "processor"


class ReviewAuthorityScope(StrEnum):
    TECHNICAL_PROCESSOR = "technical-processor"
    REFERENCE_READER = "reference-reader"
    REVIEW_COLLECTION_CURATOR = "review-collection-curator"
    SCIENTIFIC_CLAIM_REVIEWER = "scientific-claim-reviewer"


@dataclass(frozen=True)
class ReviewActorProvenance:
    actor_id: str
    actor_kind: ReviewActorKind
    authority_scope: ReviewAuthorityScope
    authority_domain: str
    verification_record_id: str
    verification_method: str

    def __post_init__(self) -> None:
        _bounded(self.actor_id, field="actor_id")
        _bounded(self.authority_domain, field="authority_domain")
        _content_id(self.verification_record_id, field="verification_record_id")
        _bounded(self.verification_method, field="verification_method")
        if self.authority_scope is ReviewAuthorityScope.TECHNICAL_PROCESSOR:
            if self.actor_kind is not ReviewActorKind.PROCESSOR:
                raise ReviewRecordError(
                    "technical authority requires a processor actor"
                )
        elif self.actor_kind is not ReviewActorKind.PERSON:
            raise ReviewRecordError("human review authority requires a person")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "actor_id",
                "actor_kind",
                "authority_scope",
                "authority_domain",
                "verification_record_id",
                "verification_method",
            },
            label="review actor",
        )
        return cls(
            actor_id=_string(data["actor_id"], field="actor_id"),
            actor_kind=_enum_value(
                ReviewActorKind,
                data["actor_kind"],
                field="actor_kind",
            ),
            authority_scope=_enum_value(
                ReviewAuthorityScope,
                data["authority_scope"],
                field="authority_scope",
            ),
            authority_domain=_string(
                data["authority_domain"], field="authority_domain"
            ),
            verification_record_id=_string(
                data["verification_record_id"],
                field="verification_record_id",
            ),
            verification_method=_string(
                data["verification_method"], field="verification_method"
            ),
        )


class ReviewTransitionKind(StrEnum):
    INITIAL = "initial"
    SUPERSESSION = "supersession"
    CORRECTION = "correction"


class TechnicalReviewKind(StrEnum):
    DISCOVERY = "discovery"
    METADATA_VERIFICATION = "metadata-verification"
    FULL_TEXT_LOCATION = "full-text-location"
    TRANSCRIPTION = "transcription"


class TechnicalReviewOutcome(StrEnum):
    OBSERVED = "observed"
    PASSED = "passed"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not-applicable"


class HumanReviewDimension(StrEnum):
    READING = "reading"
    CLAIM_SUPPORT_CHECK = "claim-support-check"
    REVIEW_COLLECTION_INCLUSION = "review-collection-inclusion"


class ReadingDecision(StrEnum):
    READ = "read"
    NOT_ESTABLISHED = "not-established"


class ClaimSupportCheckDecision(StrEnum):
    CHECKED = "checked"
    NOT_ESTABLISHED = "not-established"


class ReviewInclusionDecision(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNRESOLVED = "unresolved"


_DECISIONS_BY_DIMENSION = {
    HumanReviewDimension.READING: frozenset(
        item.value for item in ReadingDecision
    ),
    HumanReviewDimension.CLAIM_SUPPORT_CHECK: frozenset(
        item.value for item in ClaimSupportCheckDecision
    ),
    HumanReviewDimension.REVIEW_COLLECTION_INCLUSION: frozenset(
        item.value for item in ReviewInclusionDecision
    ),
}
_SCOPE_BY_DIMENSION = {
    HumanReviewDimension.READING: ReviewAuthorityScope.REFERENCE_READER,
    HumanReviewDimension.CLAIM_SUPPORT_CHECK: (
        ReviewAuthorityScope.SCIENTIFIC_CLAIM_REVIEWER
    ),
    HumanReviewDimension.REVIEW_COLLECTION_INCLUSION: (
        ReviewAuthorityScope.REVIEW_COLLECTION_CURATOR
    ),
}


@dataclass(frozen=True)
class TechnicalReviewRecord:
    schema_version: int
    authority_kind: str
    producer: ProducerIdentity
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    subject_id: str
    context_id: str
    technical_kind: TechnicalReviewKind
    outcome: TechnicalReviewOutcome
    transition_kind: ReviewTransitionKind
    actor: ReviewActorProvenance
    evidence_ids: tuple[str, ...]
    rationale: str
    observed_at: str
    supersedes_record_id: str | None
    record_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _REVIEW_SCHEMA_VERSION:
            raise ReviewRecordError("unsupported technical-review schema")
        if self.authority_kind != "technical-review-observation":
            raise ReviewRecordError(
                "unsupported technical-review authority kind"
            )
        _validate_producer(self.producer)
        _validate_effective_limits(
            self.effective_limits,
            self.effective_limits_id,
        )
        _content_id(self.subject_id, field="subject_id")
        _bounded(self.context_id, field="context_id")
        if not isinstance(self.technical_kind, TechnicalReviewKind):
            raise ReviewRecordError("invalid technical review kind")
        if not isinstance(self.outcome, TechnicalReviewOutcome):
            raise ReviewRecordError("invalid technical review outcome")
        _validate_common_record(
            transition_kind=self.transition_kind,
            actor=self.actor,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
            recorded_at=self.observed_at,
            supersedes_record_id=self.supersedes_record_id,
        )
        if (
            self.actor.actor_kind is not ReviewActorKind.PROCESSOR
            or self.actor.authority_scope
            is not ReviewAuthorityScope.TECHNICAL_PROCESSOR
        ):
            raise ReviewRecordError(
                "technical observations require technical processor authority"
            )
        expected = self.identity_for(
            schema_version=self.schema_version,
            authority_kind=self.authority_kind,
            producer=self.producer,
            effective_limits=self.effective_limits,
            effective_limits_id=self.effective_limits_id,
            subject_id=self.subject_id,
            context_id=self.context_id,
            technical_kind=self.technical_kind,
            outcome=self.outcome,
            transition_kind=self.transition_kind,
            actor=self.actor,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
            observed_at=self.observed_at,
            supersedes_record_id=self.supersedes_record_id,
        )
        if self.record_id != expected:
            raise ReviewRecordError("technical-review identity does not match")

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        context_id: str,
        technical_kind: TechnicalReviewKind,
        outcome: TechnicalReviewOutcome,
        producer: ProducerIdentity,
        transition_kind: ReviewTransitionKind,
        actor: ReviewActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        observed_at: str,
        supersedes_record_id: str | None = None,
    ) -> Self:
        payload = {
            "schema_version": _REVIEW_SCHEMA_VERSION,
            "authority_kind": "technical-review-observation",
            "producer": producer,
            "effective_limits": REVIEW_IO_LIMITS,
            "effective_limits_id": REVIEW_IO_LIMITS.evidence_id,
            "subject_id": subject_id,
            "context_id": context_id,
            "technical_kind": technical_kind,
            "outcome": outcome,
            "transition_kind": transition_kind,
            "actor": actor,
            "evidence_ids": tuple(sorted(evidence_ids)),
            "rationale": rationale,
            "observed_at": observed_at,
            "supersedes_record_id": supersedes_record_id,
        }
        return cls(
            schema_version=_REVIEW_SCHEMA_VERSION,
            authority_kind="technical-review-observation",
            producer=producer,
            effective_limits=REVIEW_IO_LIMITS,
            effective_limits_id=REVIEW_IO_LIMITS.evidence_id,
            subject_id=subject_id,
            context_id=context_id,
            technical_kind=technical_kind,
            outcome=outcome,
            transition_kind=transition_kind,
            actor=actor,
            evidence_ids=cast(tuple[str, ...], payload["evidence_ids"]),
            rationale=rationale,
            observed_at=observed_at,
            supersedes_record_id=supersedes_record_id,
            record_id=cls.identity_for(**payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "authority_kind",
                "producer",
                "effective_limits",
                "effective_limits_id",
                "subject_id",
                "context_id",
                "technical_kind",
                "outcome",
                "transition_kind",
                "actor",
                "evidence_ids",
                "rationale",
                "observed_at",
                "supersedes_record_id",
                "record_id",
            },
            label="technical review record",
        )
        return cls(
            schema_version=_integer(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_string(
                data["authority_kind"], field="authority_kind"
            ),
            producer=ProducerIdentity.from_dict(data["producer"]),
            effective_limits=_limits_from_dict(data["effective_limits"]),
            effective_limits_id=_string(
                data["effective_limits_id"], field="effective_limits_id"
            ),
            subject_id=_string(data["subject_id"], field="subject_id"),
            context_id=_string(data["context_id"], field="context_id"),
            technical_kind=_enum_value(
                TechnicalReviewKind,
                data["technical_kind"],
                field="technical_kind",
            ),
            outcome=_enum_value(
                TechnicalReviewOutcome,
                data["outcome"],
                field="outcome",
            ),
            transition_kind=_enum_value(
                ReviewTransitionKind,
                data["transition_kind"],
                field="transition_kind",
            ),
            actor=ReviewActorProvenance.from_dict(data["actor"]),
            evidence_ids=_string_array(
                data["evidence_ids"], field="evidence_ids"
            ),
            rationale=_string(data["rationale"], field="rationale"),
            observed_at=_string(data["observed_at"], field="observed_at"),
            supersedes_record_id=_optional_string(
                data["supersedes_record_id"], field="supersedes_record_id"
            ),
            record_id=_string(data["record_id"], field="record_id"),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        record = cls.from_dict(
            _canonical_object(text, label="technical review")
        )
        if record.to_json() != text:
            raise ReviewRecordError(
                "technical-review serialization is not canonical"
            )
        return record

    @staticmethod
    def identity_for(**payload: object) -> str:
        return _stable_id("technical-review", payload)

    def to_json(self) -> str:
        return _pretty_json(self)


@dataclass(frozen=True)
class HumanReviewDecision:
    schema_version: int
    authority_kind: str
    producer: ProducerIdentity
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    subject_id: str
    context_id: str
    dimension: HumanReviewDimension
    decision: str
    transition_kind: ReviewTransitionKind
    actor: ReviewActorProvenance
    evidence_ids: tuple[str, ...]
    rationale: str
    decided_at: str
    supersedes_decision_id: str | None
    decision_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _REVIEW_SCHEMA_VERSION:
            raise ReviewRecordError("unsupported human-review schema")
        if self.authority_kind != "human-review-decision":
            raise ReviewRecordError("unsupported human-review authority kind")
        _validate_producer(self.producer)
        _validate_effective_limits(
            self.effective_limits,
            self.effective_limits_id,
        )
        _content_id(self.subject_id, field="subject_id")
        _bounded(self.context_id, field="context_id")
        if not isinstance(self.dimension, HumanReviewDimension):
            raise ReviewRecordError("invalid human review dimension")
        if self.decision not in _DECISIONS_BY_DIMENSION[self.dimension]:
            raise ReviewRecordError(
                f"invalid {self.dimension.value} decision value"
            )
        _validate_common_record(
            transition_kind=self.transition_kind,
            actor=self.actor,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
            recorded_at=self.decided_at,
            supersedes_record_id=self.supersedes_decision_id,
        )
        required_scope = _SCOPE_BY_DIMENSION[self.dimension]
        if (
            self.actor.actor_kind is not ReviewActorKind.PERSON
            or self.actor.authority_scope is not required_scope
        ):
            raise ReviewRecordError(
                f"{self.dimension.value} requires {required_scope.value} "
                "person authority"
            )
        reference_owned = self.dimension in {
            HumanReviewDimension.READING,
            HumanReviewDimension.REVIEW_COLLECTION_INCLUSION,
        }
        if reference_owned and self.actor.authority_domain != _REFERENCE_DOMAIN:
            raise ReviewRecordError(
                f"{self.dimension.value} authority domain must be "
                f"{_REFERENCE_DOMAIN}"
            )
        if (
            self.dimension is HumanReviewDimension.CLAIM_SUPPORT_CHECK
            and self.actor.authority_domain == _REFERENCE_DOMAIN
        ):
            raise ReviewRecordError(
                "claim-support authority belongs to the owning scientific "
                "application, not projectkoios-references"
            )
        if self.dimension is HumanReviewDimension.CLAIM_SUPPORT_CHECK:
            _content_id(self.context_id, field="claim context_id")
        expected = self.identity_for(
            schema_version=self.schema_version,
            authority_kind=self.authority_kind,
            producer=self.producer,
            effective_limits=self.effective_limits,
            effective_limits_id=self.effective_limits_id,
            subject_id=self.subject_id,
            context_id=self.context_id,
            dimension=self.dimension,
            decision=self.decision,
            transition_kind=self.transition_kind,
            actor=self.actor,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
            decided_at=self.decided_at,
            supersedes_decision_id=self.supersedes_decision_id,
        )
        if self.decision_id != expected:
            raise ReviewRecordError(
                "human-review decision identity does not match"
            )

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        context_id: str,
        dimension: HumanReviewDimension,
        decision: ReadingDecision
        | ClaimSupportCheckDecision
        | ReviewInclusionDecision,
        producer: ProducerIdentity,
        transition_kind: ReviewTransitionKind,
        actor: ReviewActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        decided_at: str,
        supersedes_decision_id: str | None = None,
    ) -> Self:
        payload = {
            "schema_version": _REVIEW_SCHEMA_VERSION,
            "authority_kind": "human-review-decision",
            "producer": producer,
            "effective_limits": REVIEW_IO_LIMITS,
            "effective_limits_id": REVIEW_IO_LIMITS.evidence_id,
            "subject_id": subject_id,
            "context_id": context_id,
            "dimension": dimension,
            "decision": decision.value,
            "transition_kind": transition_kind,
            "actor": actor,
            "evidence_ids": tuple(sorted(evidence_ids)),
            "rationale": rationale,
            "decided_at": decided_at,
            "supersedes_decision_id": supersedes_decision_id,
        }
        return cls(
            schema_version=_REVIEW_SCHEMA_VERSION,
            authority_kind="human-review-decision",
            producer=producer,
            effective_limits=REVIEW_IO_LIMITS,
            effective_limits_id=REVIEW_IO_LIMITS.evidence_id,
            subject_id=subject_id,
            context_id=context_id,
            dimension=dimension,
            decision=decision.value,
            transition_kind=transition_kind,
            actor=actor,
            evidence_ids=cast(tuple[str, ...], payload["evidence_ids"]),
            rationale=rationale,
            decided_at=decided_at,
            supersedes_decision_id=supersedes_decision_id,
            decision_id=cls.identity_for(**payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "authority_kind",
                "producer",
                "effective_limits",
                "effective_limits_id",
                "subject_id",
                "context_id",
                "dimension",
                "decision",
                "transition_kind",
                "actor",
                "evidence_ids",
                "rationale",
                "decided_at",
                "supersedes_decision_id",
                "decision_id",
            },
            label="human review decision",
        )
        return cls(
            schema_version=_integer(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_string(
                data["authority_kind"], field="authority_kind"
            ),
            producer=ProducerIdentity.from_dict(data["producer"]),
            effective_limits=_limits_from_dict(data["effective_limits"]),
            effective_limits_id=_string(
                data["effective_limits_id"], field="effective_limits_id"
            ),
            subject_id=_string(data["subject_id"], field="subject_id"),
            context_id=_string(data["context_id"], field="context_id"),
            dimension=_enum_value(
                HumanReviewDimension,
                data["dimension"],
                field="dimension",
            ),
            decision=_string(data["decision"], field="decision"),
            transition_kind=_enum_value(
                ReviewTransitionKind,
                data["transition_kind"],
                field="transition_kind",
            ),
            actor=ReviewActorProvenance.from_dict(data["actor"]),
            evidence_ids=_string_array(
                data["evidence_ids"], field="evidence_ids"
            ),
            rationale=_string(data["rationale"], field="rationale"),
            decided_at=_string(data["decided_at"], field="decided_at"),
            supersedes_decision_id=_optional_string(
                data["supersedes_decision_id"],
                field="supersedes_decision_id",
            ),
            decision_id=_string(data["decision_id"], field="decision_id"),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        decision = cls.from_dict(
            _canonical_object(text, label="human review decision")
        )
        if decision.to_json() != text:
            raise ReviewRecordError(
                "human-review serialization is not canonical"
            )
        return decision

    @staticmethod
    def identity_for(**payload: object) -> str:
        return _stable_id("review-decision", payload)

    def to_json(self) -> str:
        return _pretty_json(self)


@dataclass(frozen=True, init=False)
class ReviewProjection:
    schema_version: int
    authority_kind: str
    producer: ProducerIdentity
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    technical_history: tuple[TechnicalReviewRecord, ...]
    human_decision_history: tuple[HumanReviewDecision, ...]
    current_technical_record_ids: tuple[str, ...]
    current_human_decision_ids: tuple[str, ...]
    projection_id: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ReviewRecordError(
            "review projections can only be created by replay_review_records"
        )

    def __post_init__(self) -> None:
        if self.schema_version != _REVIEW_SCHEMA_VERSION:
            raise ReviewRecordError("unsupported review projection schema")
        if self.authority_kind != "review-state-projection":
            raise ReviewRecordError("unsupported review projection kind")
        _validate_producer(self.producer)
        if self.producer != _REPLAY_PRODUCER:
            raise ReviewRecordError("unsupported review replay producer")
        _validate_effective_limits(
            self.effective_limits,
            self.effective_limits_id,
        )
        if not isinstance(self.technical_history, tuple) or any(
            not isinstance(item, TechnicalReviewRecord)
            for item in self.technical_history
        ):
            raise ReviewRecordError("technical history must contain records")
        if not isinstance(self.human_decision_history, tuple) or any(
            not isinstance(item, HumanReviewDecision)
            for item in self.human_decision_history
        ):
            raise ReviewRecordError("human history must contain decisions")
        _content_ids(
            self.current_technical_record_ids,
            field="current_technical_record_ids",
        )
        _content_ids(
            self.current_human_decision_ids,
            field="current_human_decision_ids",
        )
        payload = {
            "schema_version": self.schema_version,
            "authority_kind": self.authority_kind,
            "producer": self.producer,
            "effective_limits": self.effective_limits,
            "effective_limits_id": self.effective_limits_id,
            "technical_history": self.technical_history,
            "human_decision_history": self.human_decision_history,
            "current_technical_record_ids": self.current_technical_record_ids,
            "current_human_decision_ids": self.current_human_decision_ids,
        }
        if self.projection_id != _stable_id("review-projection", payload):
            raise ReviewRecordError("review projection identity does not match")

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="review projection")
        _exact_object(
            data,
            fields={
                "schema_version",
                "authority_kind",
                "producer",
                "effective_limits",
                "effective_limits_id",
                "technical_history",
                "human_decision_history",
                "current_technical_record_ids",
                "current_human_decision_ids",
                "projection_id",
            },
            label="review projection",
        )
        technical = data["technical_history"]
        decisions = data["human_decision_history"]
        if not isinstance(technical, list) or not isinstance(decisions, list):
            raise ReviewRecordError("projection histories must be arrays")
        replayed = replay_review_records(
            tuple(TechnicalReviewRecord.from_dict(item) for item in technical),
            tuple(HumanReviewDecision.from_dict(item) for item in decisions),
        )
        if replayed.to_json() != text:
            raise ReviewRecordError(
                "review projection is tampered or noncanonical"
            )
        return cast(Self, replayed)

    def to_json(self) -> str:
        return _pretty_json(self)


def replay_review_records(
    technical_records: tuple[TechnicalReviewRecord, ...],
    human_decisions: tuple[HumanReviewDecision, ...],
) -> ReviewProjection:
    """Replay complete immutable histories independent of input ordering."""
    if not isinstance(technical_records, tuple) or any(
        not isinstance(item, TechnicalReviewRecord)
        for item in technical_records
    ):
        raise ReviewRecordError("technical_records must be a typed tuple")
    if not isinstance(human_decisions, tuple) or any(
        not isinstance(item, HumanReviewDecision) for item in human_decisions
    ):
        raise ReviewRecordError("human_decisions must be a typed tuple")
    if len(technical_records) + len(human_decisions) > _MAX_ITEMS:
        raise ReviewRecordError("review replay exceeds the record limit")

    technical_history, current_technical = _replay_streams(
        technical_records,
        identity=lambda item: item.record_id,
        key=lambda item: (
            item.subject_id,
            item.context_id,
            item.technical_kind.value,
        ),
        transition=lambda item: item.transition_kind,
        prior=lambda item: item.supersedes_record_id,
        value=lambda item: item.outcome.value,
        label="technical review",
    )
    human_history, current_human = _replay_streams(
        human_decisions,
        identity=lambda item: item.decision_id,
        key=lambda item: (
            item.subject_id,
            item.context_id,
            item.dimension.value,
        ),
        transition=lambda item: item.transition_kind,
        prior=lambda item: item.supersedes_decision_id,
        value=lambda item: item.decision,
        label="human review",
    )
    current_technical = tuple(sorted(current_technical))
    current_human = tuple(sorted(current_human))
    payload = {
        "schema_version": _REVIEW_SCHEMA_VERSION,
        "authority_kind": "review-state-projection",
        "producer": _REPLAY_PRODUCER,
        "effective_limits": REVIEW_IO_LIMITS,
        "effective_limits_id": REVIEW_IO_LIMITS.evidence_id,
        "technical_history": technical_history,
        "human_decision_history": human_history,
        "current_technical_record_ids": current_technical,
        "current_human_decision_ids": current_human,
    }
    return _from_replay_projection(
        schema_version=_REVIEW_SCHEMA_VERSION,
        authority_kind="review-state-projection",
        producer=_REPLAY_PRODUCER,
        effective_limits=REVIEW_IO_LIMITS,
        effective_limits_id=REVIEW_IO_LIMITS.evidence_id,
        technical_history=technical_history,
        human_decision_history=human_history,
        current_technical_record_ids=current_technical,
        current_human_decision_ids=current_human,
        projection_id=_stable_id("review-projection", payload),
    )


def _from_replay_projection(**values: object) -> ReviewProjection:
    projection = object.__new__(ReviewProjection)
    for name, value in values.items():
        object.__setattr__(projection, name, value)
    projection.__post_init__()
    return projection


def _replay_streams[Record](
    records: tuple[Record, ...],
    *,
    identity: Callable[[Record], str],
    key: Callable[[Record], tuple[str, ...]],
    transition: Callable[[Record], ReviewTransitionKind],
    prior: Callable[[Record], str | None],
    value: Callable[[Record], str],
    label: str,
) -> tuple[tuple[Record, ...], tuple[str, ...]]:
    by_id = {identity(item): item for item in records}
    if len(by_id) != len(records):
        raise ReviewRecordError(f"{label} identities contain duplicates")
    groups: dict[tuple[str, ...], list[Record]] = {}
    for item in records:
        groups.setdefault(key(item), []).append(item)

    ordered: list[Record] = []
    current: list[str] = []
    for stream_key in sorted(groups):
        stream = groups[stream_key]
        roots = [
            item
            for item in stream
            if transition(item) is ReviewTransitionKind.INITIAL
        ]
        if len(roots) != 1:
            raise ReviewRecordError(
                f"{label} stream requires exactly one initial record"
            )
        root = roots[0]
        if prior(root) is not None:
            raise ReviewRecordError(
                f"{label} initial record supersedes history"
            )
        children: dict[str, list[Record]] = {}
        for item in stream:
            if item is root:
                continue
            parent_id = prior(item)
            if parent_id is None:
                raise ReviewRecordError(
                    f"{label} non-initial record omits exact supersession"
                )
            parent = by_id.get(parent_id)
            if parent is None or key(parent) != stream_key:
                raise ReviewRecordError(
                    f"{label} record supersedes missing or different state"
                )
            children.setdefault(parent_id, []).append(item)
        if any(len(items) != 1 for items in children.values()):
            raise ReviewRecordError(
                f"{label} contains concurrent conflicting transitions"
            )

        seen: set[str] = set()
        item = root
        while True:
            item_id = identity(item)
            if item_id in seen:
                raise ReviewRecordError(f"{label} supersession cycle detected")
            seen.add(item_id)
            ordered.append(item)
            next_items = children.get(item_id, [])
            if not next_items:
                current.append(item_id)
                break
            next_item = next_items[0]
            if value(next_item) == value(item):
                raise ReviewRecordError(
                    f"{label} transition does not change state"
                )
            _validate_state_change(item, next_item)
            item = next_item
        if len(seen) != len(stream):
            raise ReviewRecordError(
                f"{label} contains disconnected or cyclic history"
            )
    return tuple(ordered), tuple(current)


def _validate_state_change(previous: object, current: object) -> None:
    previous_time = _transition_time(previous)
    current_time = _transition_time(current)
    if current_time < previous_time:
        raise ReviewRecordError(
            "review transition timestamp precedes its superseded record"
        )
    if not isinstance(previous, HumanReviewDecision) or not isinstance(
        current, HumanReviewDecision
    ):
        return
    regression = (
        previous.dimension is HumanReviewDimension.READING
        and previous.decision == ReadingDecision.READ.value
        and current.decision == ReadingDecision.NOT_ESTABLISHED.value
    ) or (
        previous.dimension is HumanReviewDimension.CLAIM_SUPPORT_CHECK
        and previous.decision == ClaimSupportCheckDecision.CHECKED.value
        and current.decision == ClaimSupportCheckDecision.NOT_ESTABLISHED.value
    )
    if (
        regression
        and current.transition_kind is not ReviewTransitionKind.CORRECTION
    ):
        raise ReviewRecordError(
            f"{current.dimension.value} regression requires a correction"
        )


def _transition_time(value: object) -> datetime:
    if isinstance(value, TechnicalReviewRecord):
        recorded_at = value.observed_at
    elif isinstance(value, HumanReviewDecision):
        recorded_at = value.decided_at
    else:
        raise ReviewRecordError("review transition record type is invalid")
    return datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ")


def _validate_common_record(
    *,
    transition_kind: ReviewTransitionKind,
    actor: ReviewActorProvenance,
    evidence_ids: tuple[str, ...],
    rationale: str,
    recorded_at: str,
    supersedes_record_id: str | None,
) -> None:
    if not isinstance(transition_kind, ReviewTransitionKind):
        raise ReviewRecordError("invalid review transition kind")
    if not isinstance(actor, ReviewActorProvenance):
        raise ReviewRecordError("review actor provenance is invalid")
    _content_ids(
        evidence_ids,
        field="evidence_ids",
        maximum=_MAX_EVIDENCE_IDS,
    )
    if not evidence_ids:
        raise ReviewRecordError("review record requires evidence")
    if actor.verification_record_id not in evidence_ids:
        raise ReviewRecordError("review evidence omits actor verification")
    _bounded(rationale, field="rationale")
    if _TIMESTAMP.fullmatch(recorded_at) is None:
        raise ReviewRecordError("review timestamp must be canonical UTC")
    try:
        datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ReviewRecordError(
            "review timestamp must be a real canonical UTC date"
        ) from error
    if transition_kind is ReviewTransitionKind.INITIAL:
        if supersedes_record_id is not None:
            raise ReviewRecordError("initial review record cannot supersede")
    elif supersedes_record_id is None:
        raise ReviewRecordError("review transition requires exact supersession")
    else:
        _content_id(supersedes_record_id, field="supersedes_record_id")


def _validate_producer(value: ProducerIdentity) -> None:
    if not isinstance(value, ProducerIdentity):
        raise ReviewRecordError("review producer identity is invalid")


def _validate_effective_limits(
    limits: ReferenceIOLimits,
    limits_id: str,
) -> None:
    if limits != REVIEW_IO_LIMITS:
        raise ReviewRecordError("review effective limits are unsupported")
    if limits_id != limits.evidence_id:
        raise ReviewRecordError("review effective-limits identity differs")


def _limits_from_dict(value: object) -> ReferenceIOLimits:
    data = _exact_object(
        value,
        fields=set(REVIEW_IO_LIMITS.to_dict()),
        label="review effective limits",
    )
    try:
        return ReferenceIOLimits(**cast(Any, data))
    except (TypeError, ValueError) as error:
        raise ReviewRecordError(
            "review effective limits are invalid"
        ) from error


def _content_ids(
    values: tuple[str, ...],
    *,
    field: str,
    maximum: int = _MAX_ITEMS,
) -> None:
    if not isinstance(values, tuple) or len(values) > maximum:
        raise ReviewRecordError(f"{field} must be a bounded tuple")
    if tuple(sorted(set(values))) != values:
        raise ReviewRecordError(f"{field} must be sorted and unique")
    for item in values:
        _content_id(item, field=field)


def _content_id(value: str, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > _MAX_CONTENT_ID_BYTES
        or _CONTENT_ID.fullmatch(value) is None
    ):
        raise ReviewRecordError(f"{field} must be a content identity")


def _bounded(value: str, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > _MAX_TEXT
    ):
        raise ReviewRecordError(f"{field} must be a bounded non-empty string")


def _exact_object(
    value: object, *, fields: set[str], label: str
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ReviewRecordError(f"{label} fields are incomplete or unexpected")
    if any(not isinstance(key, str) for key in value):
        raise ReviewRecordError(f"{label} keys must be strings")
    return cast(dict[str, object], value)


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ReviewRecordError(f"{field} must be a string")
    return value


def _enum_value[EnumValue: StrEnum](
    enum_type: type[EnumValue],
    value: object,
    *,
    field: str,
) -> EnumValue:
    raw = _string(value, field=field)
    try:
        return enum_type(raw)
    except ValueError as error:
        raise ReviewRecordError(f"{field} is invalid") from error


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _integer(value: object, *, field: str) -> int:
    if type(value) is not int:
        raise ReviewRecordError(f"{field} must be an integer")
    return value


def _string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ReviewRecordError(f"{field} must be a string array")
    return tuple(cast(list[str], value))


def _canonical_object(text: str, *, label: str) -> dict[str, object]:
    validate_json_text_nesting(
        text,
        limits=REVIEW_IO_LIMITS,
        resource=f"{label} JSON",
    )
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ReviewRecordError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ):
        raise ReviewRecordError(f"{label} must be an object with string keys")
    return cast(dict[str, object], value)


def _stable_id(kind: str, value: object) -> str:
    digest = hashlib.sha256(_compact_json(value).encode()).hexdigest()
    return f"{kind}:sha256:{digest}"


def _compact_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _pretty_json(value: object) -> str:
    return (
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _json_value(item)
            for key, item in asdict(cast(Any, value)).items()
        }
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value
