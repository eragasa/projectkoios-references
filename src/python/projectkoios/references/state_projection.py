from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from itertools import islice
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from projectkoios.references.acquisition import AcquisitionProjection
from projectkoios.references.assets import (
    ASSET_AMBIGUITY_STATUSES,
    AssetCandidate,
    AssetDiscoveryPlan,
    AssetHeuristicObservation,
)
from projectkoios.references.coverage import (
    CoverageAccessState,
    CoverageObservation,
)
from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.io_limits import bounded_csv_field_size
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.review import (
    HumanReviewDimension,
    ReviewProjection,
)

if TYPE_CHECKING:
    from projectkoios.references.collection_reconciliation import (
        CollectionRowEvidence,
        ManagedPdf,
        ProcessingEvidence,
    )

STATE_PROJECTION_SCHEMA_VERSION = 1
STATE_PROJECTION_ARTIFACT_KIND = (
    "projectkoios.references.reference-state-projection"
)
STATE_PROJECTION_GENERATOR = "projectkoios-references-state-reducer"
STATE_PROJECTION_GENERATOR_VERSION = "1"

_MAX_TEXT = 4096
_MAX_CLAIMS = 4096
_MAX_INPUTS = 4096
_MAX_EXCLUSIONS = 128
_MAX_PROJECTION_BYTES = 4_000_000
_MAX_PROJECTION_CSV_BYTES = 10_000_000
_MAX_PROJECTION_CSV_FIELD_CHARACTERS = 1_000_000
_MAX_VALUE_BYTES = 100_000
_CONFIGURATION = {
    "max_claims": _MAX_CLAIMS,
    "max_inputs": _MAX_INPUTS,
    "max_exclusions": _MAX_EXCLUSIONS,
    "max_projection_bytes": _MAX_PROJECTION_BYTES,
    "max_projection_csv_bytes": _MAX_PROJECTION_CSV_BYTES,
    "max_projection_csv_field_characters": (
        _MAX_PROJECTION_CSV_FIELD_CHARACTERS
    ),
    "max_text_bytes": _MAX_TEXT,
    "max_value_bytes": _MAX_VALUE_BYTES,
}
STATE_PROJECTION_CONFIGURATION_ID = (
    "reference-state-projection-configuration:sha256:"
    + hashlib.sha256(
        json.dumps(
            _CONFIGURATION,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
)
_CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class StateProjectionError(ValueError):
    """Raised when authority-bearing state cannot be projected safely."""


class StateRecordKind(StrEnum):
    IMMUTABLE_OBSERVATION = "immutable-observation"
    IMMUTABLE_PROPOSAL = "immutable-proposal"
    HUMAN_DECISION = "human-decision"


class StateKnowledge(StrEnum):
    OBSERVED = "observed"
    UNKNOWN = "unknown"
    NOT_OBSERVED = "not-observed"
    NOT_APPLICABLE = "not-applicable"


class StateResolution(StrEnum):
    NOT_OBSERVED = "not-observed"
    SINGLE = "single-authoritative-value"
    AGREEMENT = "multi-source-agreement"
    DISCREPANCY = "unresolved-discrepancy"


class StateDimension(StrEnum):
    CANDIDATE_IDENTITY = "candidate-identity"
    CANONICAL_IDENTITY_DECISION = "canonical-identity-decision"
    BIBLIOGRAPHIC_METADATA = "bibliographic-metadata"
    COLLECTION_OBSERVATION = "collection-observation"
    READING_DECISION = "reading-decision"
    CLAIM_SUPPORT_DECISION = "claim-support-decision"
    COLLECTION_DECISION = "collection-decision"
    ASSET_DISCOVERY = "asset-discovery"
    ACQUISITION = "acquisition"
    ACCESS = "access"
    RIGHTS = "rights"
    RIGHTS_DECISION = "rights-decision"
    SCIENTIFIC_SUPPORT = "scientific-support"
    INGESTION = "ingestion"
    TECHNICAL_REVIEW = "technical-review"
    CITATION = "citation"
    MANUSCRIPT_USE = "manuscript-use"
    PUBLICATION = "publication"
    CONTRACT_ACCEPTANCE = "contract-acceptance"


@dataclass(frozen=True)
class StateFieldRule:
    dimension: StateDimension
    authority_owner: str
    allowed_record_kinds: tuple[StateRecordKind, ...]


_OBSERVATION = (StateRecordKind.IMMUTABLE_OBSERVATION,)
_PROPOSAL = (StateRecordKind.IMMUTABLE_PROPOSAL,)
_OBSERVATION_OR_PROPOSAL = _OBSERVATION + _PROPOSAL
_DECISION = (StateRecordKind.HUMAN_DECISION,)

# This table is the executable per-field authority matrix. Values from another
# owner are not preferred or overwritten; they are rejected at the adapter
# boundary or retained as a same-field discrepancy when the rule is
# multi-source.
STATE_FIELD_RULES: Mapping[str, StateFieldRule] = MappingProxyType(
    {
        "candidate_id": StateFieldRule(
            StateDimension.CANDIDATE_IDENTITY,
            "projectkoios-references",
            _PROPOSAL,
        ),
        "identity_status": StateFieldRule(
            StateDimension.CANDIDATE_IDENTITY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "proposed_citekey": StateFieldRule(
            StateDimension.CANDIDATE_IDENTITY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "citekey_status": StateFieldRule(
            StateDimension.CANDIDATE_IDENTITY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "entry_type": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "title": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "authors": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "year": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "doi": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "isbn": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "url": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "eprint": StateFieldRule(
            StateDimension.BIBLIOGRAPHIC_METADATA,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "source_bibliographies": StateFieldRule(
            StateDimension.COLLECTION_OBSERVATION,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "bibliographic_status": StateFieldRule(
            StateDimension.COLLECTION_OBSERVATION,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "reading_observation": StateFieldRule(
            StateDimension.COLLECTION_OBSERVATION,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "reading_decision": StateFieldRule(
            StateDimension.READING_DECISION,
            "projectkoios-references",
            _DECISION,
        ),
        "claim_support_check": StateFieldRule(
            StateDimension.CLAIM_SUPPORT_DECISION,
            "owning-research-repository",
            _DECISION,
        ),
        "collection_inclusion": StateFieldRule(
            StateDimension.COLLECTION_DECISION,
            "projectkoios-references",
            _DECISION,
        ),
        "asset_sha256": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "asset_byte_size": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "asset_root_alias": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "asset_relative_path": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "asset_status": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _OBSERVATION_OR_PROPOSAL,
        ),
        "asset_heuristic_observations": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _PROPOSAL,
        ),
        "asset_ambiguity_status": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _PROPOSAL,
        ),
        "asset_competing_observation_ids": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _PROPOSAL,
        ),
        "asset_alternate_version_observation_ids": StateFieldRule(
            StateDimension.ASSET_DISCOVERY,
            "projectkoios-references",
            _PROPOSAL,
        ),
        "acquisition_status": StateFieldRule(
            StateDimension.ACQUISITION,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "access_status": StateFieldRule(
            StateDimension.ACCESS,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "rights_status": StateFieldRule(
            StateDimension.RIGHTS,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "ingestion_status": StateFieldRule(
            StateDimension.INGESTION,
            "projectkoios-ingestion",
            _OBSERVATION,
        ),
        "transcript_status": StateFieldRule(
            StateDimension.INGESTION,
            "projectkoios-ingestion",
            _OBSERVATION,
        ),
        "ingestion_contract_status": StateFieldRule(
            StateDimension.INGESTION,
            "projectkoios-ingestion",
            _OBSERVATION,
        ),
        "acquisition_contract_status": StateFieldRule(
            StateDimension.ACQUISITION,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "derivation_audit_status": StateFieldRule(
            StateDimension.INGESTION,
            "projectkoios-ingestion",
            _OBSERVATION,
        ),
        "technical_review_status": StateFieldRule(
            StateDimension.TECHNICAL_REVIEW,
            "projectkoios-references",
            _OBSERVATION,
        ),
        "citation_status": StateFieldRule(
            StateDimension.CITATION,
            "projectkoios-references",
            _OBSERVATION,
        ),
    }
)

_EXACT_FIELD_VALUES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "identity_status": frozenset({"unaccepted-candidate"}),
        "citekey_status": frozenset({"proposed-noncanonical"}),
        "asset_ambiguity_status": ASSET_AMBIGUITY_STATUSES,
        "reading_decision": frozenset({"not-established", "read"}),
        "claim_support_check": frozenset({"not-established", "checked"}),
        "collection_inclusion": frozenset(
            {"unresolved", "included", "excluded"}
        ),
    }
)
_STRING_FIELDS = frozenset(
    {
        "proposed_citekey",
        "entry_type",
        "title",
        "year",
        "doi",
        "isbn",
        "url",
        "eprint",
        "bibliographic_status",
        "reading_observation",
        "asset_root_alias",
        "asset_relative_path",
        "asset_status",
        "acquisition_status",
        "access_status",
        "rights_status",
        "ingestion_status",
        "transcript_status",
        "ingestion_contract_status",
        "acquisition_contract_status",
        "derivation_audit_status",
        "citation_status",
    }
)
_STRING_ARRAY_FIELDS = frozenset(
    {
        "authors",
        "source_bibliographies",
        "asset_competing_observation_ids",
        "asset_alternate_version_observation_ids",
    }
)
_SPECIAL_FIELDS = frozenset(
    {
        "candidate_id",
        "asset_sha256",
        "asset_byte_size",
        "asset_heuristic_observations",
        "technical_review_status",
    }
)
if (
    set(_EXACT_FIELD_VALUES)
    | set(_STRING_FIELDS)
    | set(_STRING_ARRAY_FIELDS)
    | set(_SPECIAL_FIELDS)
) != set(STATE_FIELD_RULES):  # pragma: no cover - import-time invariant
    raise RuntimeError("state field value contracts are incomplete")


@dataclass(frozen=True, init=False)
class StateClaim:
    subject_id: str
    field: str
    knowledge: StateKnowledge
    value_json: str | None
    record_kind: StateRecordKind
    authority_owner: str
    authoritative_input_id: str
    source_locator: str
    actor_id: str | None = None
    authority_scope: str | None = None
    actor_verification_record_id: str | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise StateProjectionError(
            "state claims require a typed observation or decision adapter"
        )

    def __post_init__(self) -> None:
        _content_id(self.subject_id, field="state subject_id")
        if self.field not in STATE_FIELD_RULES:
            raise StateProjectionError(f"unsupported state field: {self.field}")
        if not isinstance(self.knowledge, StateKnowledge):
            raise StateProjectionError("state knowledge is invalid")
        if not isinstance(self.record_kind, StateRecordKind):
            raise StateProjectionError("state record kind is invalid")
        rule = STATE_FIELD_RULES[self.field]
        if self.record_kind not in rule.allowed_record_kinds:
            raise StateProjectionError(
                f"{self.field} does not accept {self.record_kind.value} records"
            )
        if self.authority_owner != rule.authority_owner:
            raise StateProjectionError(
                f"{self.field} authority owner must be {rule.authority_owner}"
            )
        _content_id(
            self.authoritative_input_id,
            field="authoritative_input_id",
        )
        _safe_locator(self.source_locator)
        actor_values = (
            self.actor_id,
            self.authority_scope,
            self.actor_verification_record_id,
        )
        if self.record_kind is StateRecordKind.HUMAN_DECISION:
            if any(item is None for item in actor_values):
                raise StateProjectionError(
                    "human decision claim requires actor provenance"
                )
            _bounded(self.actor_id, field="decision actor_id")
            _bounded(self.authority_scope, field="decision authority_scope")
            _content_id(
                self.actor_verification_record_id,
                field="decision actor verification",
            )
        elif any(item is not None for item in actor_values):
            raise StateProjectionError(
                "observation claim cannot carry human actor provenance"
            )
        if self.knowledge is StateKnowledge.OBSERVED:
            if self.value_json is None:
                raise StateProjectionError("observed state requires value_json")
            value = _parse_canonical_value(self.value_json)
            if value is None:
                raise StateProjectionError("observed state cannot contain null")
            _validate_state_value(self.field, value)
        elif self.value_json is not None:
            raise StateProjectionError(
                "unknown, not-observed, and not-applicable state omit "
                "value_json"
            )

    @classmethod
    def observed(
        cls,
        *,
        subject_id: str,
        field: str,
        value: object,
        record_kind: StateRecordKind,
        authoritative_input_id: str,
        source_locator: str,
        authority_owner: str | None = None,
        actor_id: str | None = None,
        authority_scope: str | None = None,
        actor_verification_record_id: str | None = None,
    ) -> StateClaim:
        rule = STATE_FIELD_RULES.get(field)
        if rule is None:
            raise StateProjectionError(f"unsupported state field: {field}")
        if record_kind is StateRecordKind.HUMAN_DECISION:
            raise StateProjectionError(
                "human decisions require a typed actor-provenanced adapter"
            )
        return _make_state_claim(
            subject_id=subject_id,
            field=field,
            knowledge=StateKnowledge.OBSERVED,
            value_json=_canonical_value(value),
            record_kind=record_kind,
            authority_owner=authority_owner or rule.authority_owner,
            authoritative_input_id=authoritative_input_id,
            source_locator=source_locator,
            actor_id=actor_id,
            authority_scope=authority_scope,
            actor_verification_record_id=actor_verification_record_id,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        subject_id: str,
        field: str,
        knowledge: StateKnowledge,
        authoritative_input_id: str,
        source_locator: str,
    ) -> StateClaim:
        del cls
        if knowledge is StateKnowledge.OBSERVED:
            raise StateProjectionError(
                "observed state requires the observed claim factory"
            )
        rule = STATE_FIELD_RULES.get(field)
        if rule is None or StateRecordKind.IMMUTABLE_OBSERVATION not in (
            rule.allowed_record_kinds
        ):
            raise StateProjectionError(
                f"{field} does not accept unavailable observations"
            )
        return _make_state_claim(
            subject_id=subject_id,
            field=field,
            knowledge=knowledge,
            value_json=None,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authority_owner=rule.authority_owner,
            authoritative_input_id=authoritative_input_id,
            source_locator=source_locator,
            actor_id=None,
            authority_scope=None,
            actor_verification_record_id=None,
        )

    def value(self) -> object | None:
        return (
            None
            if self.value_json is None
            else _parse_canonical_value(self.value_json)
        )


@dataclass(frozen=True)
class ProjectedValue:
    knowledge: StateKnowledge
    value_json: str | None
    authoritative_input_ids: tuple[str, ...]
    record_kinds: tuple[StateRecordKind, ...]
    source_locators: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge, StateKnowledge):
            raise StateProjectionError("projected knowledge is invalid")
        _ordered_unique_content_ids(
            self.authoritative_input_ids,
            field="projected authoritative inputs",
        )
        if not self.authoritative_input_ids:
            raise StateProjectionError("projected value has no authority input")
        if (
            not isinstance(self.record_kinds, tuple)
            or not self.record_kinds
            or any(
                not isinstance(item, StateRecordKind)
                for item in self.record_kinds
            )
        ):
            raise StateProjectionError("projected record kinds are invalid")
        if tuple(sorted(set(self.record_kinds), key=str)) != self.record_kinds:
            raise StateProjectionError(
                "projected record kinds are not canonical"
            )
        if tuple(sorted(set(self.source_locators))) != self.source_locators:
            raise StateProjectionError("source locators are not canonical")
        for locator in self.source_locators:
            _safe_locator(locator)
        _bounded_csv_projection_field(
            self.authoritative_input_ids,
            field="projected authoritative inputs",
        )
        _bounded_csv_projection_field(
            tuple(item.value for item in self.record_kinds),
            field="projected record kinds",
        )
        _bounded_csv_projection_field(
            self.source_locators,
            field="projected source locators",
        )
        if self.knowledge is StateKnowledge.OBSERVED:
            if self.value_json is None:
                raise StateProjectionError("observed projected value is empty")
            _parse_canonical_value(self.value_json)
        elif self.value_json is not None:
            raise StateProjectionError(
                "non-observed projected value has a value"
            )

    def value(self) -> object | None:
        return (
            None
            if self.value_json is None
            else _parse_canonical_value(self.value_json)
        )


@dataclass(frozen=True)
class ProjectedField:
    field: str
    dimension: StateDimension
    authority_owner: str
    resolution: StateResolution
    values: tuple[ProjectedValue, ...]

    def __post_init__(self) -> None:
        rule = STATE_FIELD_RULES.get(self.field)
        if rule is None:
            raise StateProjectionError(f"unsupported state field: {self.field}")
        if self.dimension is not rule.dimension:
            raise StateProjectionError(f"{self.field} dimension is invalid")
        if self.authority_owner != rule.authority_owner:
            raise StateProjectionError(
                f"{self.field} authority owner is invalid"
            )
        if not isinstance(self.resolution, StateResolution):
            raise StateProjectionError("state resolution is invalid")
        if not isinstance(self.values, tuple) or any(
            not isinstance(item, ProjectedValue) for item in self.values
        ):
            raise StateProjectionError("projected values must be a typed tuple")
        for value in self.values:
            if any(
                kind not in rule.allowed_record_kinds
                for kind in value.record_kinds
            ):
                raise StateProjectionError(
                    f"{self.field} projected record kind is unsupported"
                )
            if value.knowledge is StateKnowledge.OBSERVED:
                _validate_state_value(self.field, value.value())
        identities = tuple(
            (item.knowledge.value, item.value_json or "")
            for item in self.values
        )
        if identities != tuple(sorted(identities)) or len(identities) != len(
            set(identities)
        ):
            raise StateProjectionError("projected values are not canonical")
        expected = _resolution(self.values)
        if self.resolution is not expected:
            raise StateProjectionError(
                f"{self.field} resolution is inconsistent"
            )


@dataclass(frozen=True, init=False)
class ReferenceStateProjection:
    schema_version: int
    artifact_kind: str
    generator_name: str
    generator_version: str
    configuration_id: str
    subject_id: str
    authoritative_input_ids: tuple[str, ...]
    fields: tuple[ProjectedField, ...]
    exclusions: tuple[str, ...]
    exact_replay: bool
    projection_id: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise StateProjectionError(
            "state projections can only be created by deterministic replay"
        )

    def __post_init__(self) -> None:
        if self.schema_version != STATE_PROJECTION_SCHEMA_VERSION:
            raise StateProjectionError("unsupported state projection schema")
        if self.artifact_kind != STATE_PROJECTION_ARTIFACT_KIND:
            raise StateProjectionError("unsupported state projection kind")
        if (
            self.generator_name != STATE_PROJECTION_GENERATOR
            or self.generator_version != STATE_PROJECTION_GENERATOR_VERSION
        ):
            raise StateProjectionError("unsupported state projection generator")
        if self.configuration_id != STATE_PROJECTION_CONFIGURATION_ID:
            raise StateProjectionError(
                "unsupported state projection configuration"
            )
        _content_id(self.subject_id, field="projection subject_id")
        _ordered_unique_content_ids(
            self.authoritative_input_ids,
            field="projection authoritative inputs",
        )
        if not self.authoritative_input_ids:
            raise StateProjectionError("state projection has no inputs")
        if len(self.authoritative_input_ids) > _MAX_INPUTS:
            raise StateProjectionError(
                "state projection inputs exceed the record limit"
            )
        _bounded_csv_projection_field(
            self.authoritative_input_ids,
            field="projection authoritative inputs",
        )
        if tuple(item.field for item in self.fields) != tuple(
            sorted(STATE_FIELD_RULES)
        ):
            raise StateProjectionError(
                "state projection field coverage is incomplete"
            )
        if tuple(sorted(set(self.exclusions))) != self.exclusions:
            raise StateProjectionError(
                "projection exclusions are not canonical"
            )
        if len(self.exclusions) > _MAX_EXCLUSIONS:
            raise StateProjectionError(
                "projection exclusions exceed the record limit"
            )
        for item in self.exclusions:
            _bounded(item, field="projection exclusion")
        _bounded_csv_projection_field(
            self.exclusions,
            field="projection exclusions",
        )
        if self.exact_replay is not True:
            raise StateProjectionError(
                "state projection must claim exact replay"
            )
        used = {
            input_id
            for field in self.fields
            for value in field.values
            for input_id in value.authoritative_input_ids
        }
        if not used <= set(self.authoritative_input_ids):
            raise StateProjectionError(
                "projected value cites an undeclared input"
            )
        if self.projection_id != _stable_id(
            "reference-state-projection", self._identity_payload()
        ):
            raise StateProjectionError(
                "state projection identity does not match"
            )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "authoritative_input_ids": self.authoritative_input_ids,
            "exact_replay": self.exact_replay,
            "exclusions": self.exclusions,
            "fields": self.fields,
            "configuration_id": self.configuration_id,
            "generator_name": self.generator_name,
            "generator_version": self.generator_version,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
        }

    def to_json(self) -> str:
        return _pretty_json(
            {**self._identity_payload(), "projection_id": self.projection_id}
        )

    @classmethod
    def from_json(cls, text: str) -> ReferenceStateProjection:
        if (
            not isinstance(text, str)
            or len(text.encode("utf-8")) > _MAX_PROJECTION_BYTES
        ):
            raise StateProjectionError(
                "state projection JSON exceeds its byte limit"
            )
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, RecursionError) as error:
            raise StateProjectionError(
                "state projection JSON is invalid"
            ) from error
        if _pretty_json(data) != text:
            raise StateProjectionError("state projection JSON is not canonical")
        expected = {
            "artifact_kind",
            "authoritative_input_ids",
            "configuration_id",
            "exact_replay",
            "exclusions",
            "fields",
            "generator_name",
            "generator_version",
            "projection_id",
            "schema_version",
            "subject_id",
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise StateProjectionError(
                "state projection object fields are invalid"
            )
        raw_fields = data["fields"]
        if not isinstance(raw_fields, list):
            raise StateProjectionError(
                "state projection fields must be an array"
            )
        fields: list[ProjectedField] = []
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict) or set(raw_field) != {
                "authority_owner",
                "dimension",
                "field",
                "resolution",
                "values",
            }:
                raise StateProjectionError("projected field object is invalid")
            raw_values = raw_field["values"]
            if (
                not isinstance(raw_values, list)
                or len(raw_values) > _MAX_CLAIMS
            ):
                raise StateProjectionError(
                    "projected values must be a bounded array"
                )
            values: list[ProjectedValue] = []
            for raw_value in raw_values:
                if not isinstance(raw_value, dict) or set(raw_value) != {
                    "authoritative_input_ids",
                    "knowledge",
                    "record_kinds",
                    "source_locators",
                    "value_json",
                }:
                    raise StateProjectionError(
                        "projected value object is invalid"
                    )
                values.append(
                    ProjectedValue(
                        knowledge=_enum(
                            StateKnowledge,
                            raw_value["knowledge"],
                            field="knowledge",
                        ),
                        value_json=_optional_string(
                            raw_value["value_json"], field="value_json"
                        ),
                        authoritative_input_ids=_strings(
                            raw_value["authoritative_input_ids"],
                            field="authoritative_input_ids",
                        ),
                        record_kinds=tuple(
                            _enum(StateRecordKind, item, field="record_kind")
                            for item in _strings(
                                raw_value["record_kinds"], field="record_kinds"
                            )
                        ),
                        source_locators=_strings(
                            raw_value["source_locators"],
                            field="source_locators",
                        ),
                    )
                )
            fields.append(
                ProjectedField(
                    field=_string(raw_field["field"], field="field"),
                    dimension=_enum(
                        StateDimension,
                        raw_field["dimension"],
                        field="dimension",
                    ),
                    authority_owner=_string(
                        raw_field["authority_owner"], field="authority_owner"
                    ),
                    resolution=_enum(
                        StateResolution,
                        raw_field["resolution"],
                        field="resolution",
                    ),
                    values=tuple(values),
                )
            )
        projection = _make_projection(
            schema_version=_integer(
                data["schema_version"], field="schema_version"
            ),
            artifact_kind=_string(data["artifact_kind"], field="artifact_kind"),
            generator_name=_string(
                data["generator_name"], field="generator_name"
            ),
            generator_version=_string(
                data["generator_version"], field="generator_version"
            ),
            configuration_id=_string(
                data["configuration_id"], field="configuration_id"
            ),
            subject_id=_string(data["subject_id"], field="subject_id"),
            authoritative_input_ids=_strings(
                data["authoritative_input_ids"], field="authoritative_input_ids"
            ),
            fields=tuple(fields),
            exclusions=_strings(data["exclusions"], field="exclusions"),
            exact_replay=_boolean(data["exact_replay"], field="exact_replay"),
            projection_id=_string(data["projection_id"], field="projection_id"),
        )
        if projection.to_json() != text:
            raise StateProjectionError("state projection replay differs")
        return projection

    def field(self, name: str) -> ProjectedField:
        for item in self.fields:
            if item.field == name:
                return item
        raise KeyError(name)


def replay_reference_state(
    *,
    subject_id: str,
    claims: Iterable[StateClaim],
    authoritative_input_ids: Iterable[str],
    exclusions: Iterable[str] = (),
) -> ReferenceStateProjection:
    """Reduce immutable observations and human decisions without preference."""
    _content_id(subject_id, field="state subject_id")
    claim_values = tuple(islice(iter(claims), _MAX_CLAIMS + 1))
    if len(claim_values) > _MAX_CLAIMS:
        raise StateProjectionError("state claims exceed the record limit")
    if any(not isinstance(item, StateClaim) for item in claim_values):
        raise StateProjectionError("claims must contain StateClaim values")
    if any(item.subject_id != subject_id for item in claim_values):
        raise StateProjectionError(
            "state claim subject differs from projection"
        )
    raw_input_ids = tuple(
        islice(iter(authoritative_input_ids), _MAX_INPUTS + 1)
    )
    if len(raw_input_ids) > _MAX_INPUTS:
        raise StateProjectionError(
            "state projection inputs exceed the record limit"
        )
    input_ids = tuple(sorted(set(raw_input_ids)))
    _ordered_unique_content_ids(input_ids, field="authoritative_input_ids")
    if not input_ids:
        raise StateProjectionError(
            "state projection requires authoritative inputs"
        )
    undeclared = {item.authoritative_input_id for item in claim_values} - set(
        input_ids
    )
    if undeclared:
        raise StateProjectionError(
            f"state claims cite undeclared inputs: {sorted(undeclared)}"
        )
    grouped: dict[str, list[StateClaim]] = {
        name: [] for name in STATE_FIELD_RULES
    }
    for claim in claim_values:
        grouped[claim.field].append(claim)
    fields: list[ProjectedField] = []
    for name in sorted(STATE_FIELD_RULES):
        rule = STATE_FIELD_RULES[name]
        by_value: dict[tuple[StateKnowledge, str | None], list[StateClaim]] = {}
        for claim in grouped[name]:
            by_value.setdefault((claim.knowledge, claim.value_json), []).append(
                claim
            )
        values = tuple(
            ProjectedValue(
                knowledge=knowledge,
                value_json=value_json,
                authoritative_input_ids=tuple(
                    sorted({item.authoritative_input_id for item in items})
                ),
                record_kinds=tuple(
                    sorted({item.record_kind for item in items}, key=str)
                ),
                source_locators=tuple(
                    sorted({item.source_locator for item in items})
                ),
            )
            for (knowledge, value_json), items in sorted(
                by_value.items(),
                key=lambda item: (item[0][0].value, item[0][1] or ""),
            )
        )
        fields.append(
            ProjectedField(
                field=name,
                dimension=rule.dimension,
                authority_owner=rule.authority_owner,
                resolution=_resolution(values),
                values=values,
            )
        )
    raw_exclusions = tuple(islice(iter(exclusions), _MAX_EXCLUSIONS + 1))
    if len(raw_exclusions) > _MAX_EXCLUSIONS:
        raise StateProjectionError(
            "state projection exclusions exceed the record limit"
        )
    exclusion_values = tuple(sorted(set(raw_exclusions)))
    payload = {
        "artifact_kind": STATE_PROJECTION_ARTIFACT_KIND,
        "authoritative_input_ids": input_ids,
        "exact_replay": True,
        "exclusions": exclusion_values,
        "fields": tuple(fields),
        "configuration_id": STATE_PROJECTION_CONFIGURATION_ID,
        "generator_name": STATE_PROJECTION_GENERATOR,
        "generator_version": STATE_PROJECTION_GENERATOR_VERSION,
        "schema_version": STATE_PROJECTION_SCHEMA_VERSION,
        "subject_id": subject_id,
    }
    projection = _make_projection(
        **payload,
        projection_id=_stable_id("reference-state-projection", payload),
    )
    if len(projection.to_json().encode("utf-8")) > _MAX_PROJECTION_BYTES:
        raise StateProjectionError(
            "state projection exceeds its aggregate byte limit"
        )
    return projection


def candidate_state_claims(
    candidate: ReferenceCandidate,
) -> tuple[StateClaim, ...]:
    if not isinstance(candidate, ReferenceCandidate):
        raise TypeError("candidate must be a ReferenceCandidate")
    values: tuple[tuple[str, object | None], ...] = (
        ("candidate_id", candidate.candidate_id),
        ("identity_status", candidate.lifecycle_status),
        ("proposed_citekey", candidate.proposed_citekey),
        ("citekey_status", candidate.citekey_status),
        ("entry_type", candidate.entry_type),
        ("title", candidate.title),
        ("authors", candidate.authors),
        ("year", candidate.year),
        ("doi", candidate.doi),
        ("isbn", candidate.isbn),
        ("url", candidate.url),
        ("eprint", candidate.eprint),
    )
    claims = []
    for field, value in values:
        if value is None:
            continue
        claims.append(
            StateClaim.observed(
                subject_id=candidate.candidate_id,
                field=field,
                value=value,
                record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
                authoritative_input_id=candidate.candidate_id,
                source_locator=f"candidate/{field}",
            )
        )
    return tuple(claims)


def acquisition_state_claims(
    *,
    subject_id: str,
    projection: AcquisitionProjection,
) -> tuple[StateClaim, ...]:
    if not isinstance(projection, AcquisitionProjection):
        raise TypeError("projection must be an AcquisitionProjection")
    values: tuple[tuple[str, object], ...] = (
        ("identity_status", projection.identity_status),
        ("proposed_citekey", projection.proposed_citekey),
        ("citekey_status", projection.citekey_status),
        ("asset_sha256", projection.source_sha256),
        ("asset_byte_size", projection.source_byte_size),
        ("asset_root_alias", projection.root_alias),
        ("asset_relative_path", projection.relative_path),
        ("acquisition_status", projection.acquisition.status),
        ("access_status", projection.access.status),
        ("rights_status", projection.rights.status),
        ("acquisition_contract_status", projection.contract_status),
    )
    if projection.doi is not None:
        values += (("doi", projection.doi),)
    return tuple(
        StateClaim.observed(
            subject_id=subject_id,
            field=field,
            value=value,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=projection.manifest_id,
            source_locator=(
                f"acquisition/{projection.proposed_citekey}/{field}"
            ),
            authority_owner=None,
        )
        for field, value in values
    )


def coverage_state_claims(
    *,
    subject_id: str,
    proposed_citekey: str,
    observation: CoverageObservation,
) -> tuple[StateClaim, ...]:
    if not isinstance(observation, CoverageObservation):
        raise TypeError("observation must be a CoverageObservation")
    evidence = observation.by_citekey().get(proposed_citekey)
    claims: list[StateClaim] = []
    if evidence is None:
        claims.append(
            StateClaim.observed(
                subject_id=subject_id,
                field="asset_status",
                value="coverage-result-not-recorded",
                record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                authoritative_input_id=observation.coverage_id,
                source_locator=f"coverage/{proposed_citekey}/not-recorded",
            )
        )
        return tuple(claims)
    if evidence.access_state is not CoverageAccessState.NONE:
        claims.append(
            StateClaim.observed(
                subject_id=subject_id,
                field="access_status",
                value=evidence.access_state.value,
                record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                authoritative_input_id=observation.coverage_id,
                source_locator=f"coverage/{proposed_citekey}/access",
            )
        )
    if evidence.no_match:
        claims.append(
            StateClaim.observed(
                subject_id=subject_id,
                field="asset_status",
                value="searched-no-match",
                record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                authoritative_input_id=observation.coverage_id,
                source_locator=f"coverage/{proposed_citekey}/no-match",
            )
        )
    for index, candidate in enumerate(evidence.candidates):
        values: tuple[tuple[str, object], ...] = (
            ("asset_sha256", candidate.sha256),
            ("asset_byte_size", candidate.byte_size),
            ("asset_root_alias", candidate.root_alias),
            ("asset_relative_path", candidate.relative_path),
            (
                "asset_status",
                f"coverage-candidate:{candidate.version_relation.value}",
            ),
        )
        claims.extend(
            StateClaim.observed(
                subject_id=subject_id,
                field=field,
                value=value,
                record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                authoritative_input_id=observation.coverage_id,
                source_locator=(
                    f"coverage/{proposed_citekey}/candidate-{index}/{field}"
                ),
            )
            for field, value in values
        )
    return tuple(claims)


def collection_state_claims(
    *,
    subject_id: str,
    row: CollectionRowEvidence,
    authoritative_input_id: str,
) -> tuple[StateClaim, ...]:
    values: tuple[tuple[str, object], ...] = (
        ("source_bibliographies", row.source_bibliographies),
        ("bibliographic_status", row.bibliographic_status),
        ("reading_observation", row.reading_status),
    )
    return tuple(
        StateClaim.observed(
            subject_id=subject_id,
            field=field,
            value=value,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=authoritative_input_id,
            source_locator=(
                f"collection-row/{row.row_index}/{field}"
                if row.row_index is not None
                else f"collection-row/normalized/{field}"
            ),
        )
        for field, value in values
    )


def managed_asset_state_claims(
    *,
    subject_id: str,
    asset: ManagedPdf,
) -> tuple[StateClaim, ...]:
    record_id = _stable_id("managed-asset-observation", asdict(asset))
    values: tuple[tuple[str, object], ...] = (
        ("asset_sha256", asset.sha256),
        ("asset_byte_size", asset.byte_size),
        ("asset_relative_path", asset.filename),
        (
            "asset_status",
            "managed-verified"
            if asset.historically_verified
            else "managed-present",
        ),
        ("access_status", "managed-local-access"),
    )
    return tuple(
        StateClaim.observed(
            subject_id=subject_id,
            field=field,
            value=value,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=record_id,
            source_locator=f"managed-asset/{field}",
        )
        for field, value in values
    )


def asset_candidate_state_claims(
    *,
    subject_id: str,
    candidate: AssetCandidate,
    plan: AssetDiscoveryPlan,
) -> tuple[StateClaim, ...]:
    if not isinstance(candidate, AssetCandidate):
        raise TypeError("candidate must be an AssetCandidate")
    if not isinstance(plan, AssetDiscoveryPlan):
        raise TypeError("plan must be an AssetDiscoveryPlan")
    if candidate not in plan.candidates:
        raise StateProjectionError(
            "asset candidate is not retained by the supplied plan"
        )
    record_id = plan.plan_id
    connected = plan.connected_candidates((candidate.candidate_id,))
    competing = tuple(
        sorted(
            item.observation_id
            for item in connected
            if item.candidate_id != candidate.candidate_id
        )
    )
    alternate_versions = tuple(
        sorted(
            item.observation_id
            for item in connected
            if item.observation_id != candidate.observation_id
            and item.sha256 != candidate.sha256
        )
    )
    values: tuple[tuple[str, object], ...] = (
        ("identity_status", candidate.identity_status),
        ("proposed_citekey", candidate.proposed_citekey),
        ("citekey_status", candidate.citekey_status),
        ("asset_sha256", candidate.sha256),
        ("asset_byte_size", candidate.byte_size),
        ("asset_root_alias", candidate.root_alias),
        ("asset_relative_path", candidate.relative_path),
        ("asset_status", candidate.match_status),
        (
            "asset_heuristic_observations",
            tuple(asdict(item) for item in candidate.heuristic_observations),
        ),
        (
            "asset_ambiguity_status",
            plan.ambiguity_status(candidate.candidate_id),
        ),
        ("asset_competing_observation_ids", competing),
        (
            "asset_alternate_version_observation_ids",
            alternate_versions,
        ),
    )
    return tuple(
        StateClaim.observed(
            subject_id=subject_id,
            field=field,
            value=value,
            record_kind=StateRecordKind.IMMUTABLE_PROPOSAL,
            authoritative_input_id=record_id,
            source_locator=(
                f"asset-plan/{candidate.root_alias}/"
                f"{candidate.relative_path}/{field}"
            ),
        )
        for field, value in values
    )


def catalog_asset_state_claims(
    *,
    subject_id: str,
    asset: SourceAssetRecord,
) -> tuple[StateClaim, ...]:
    record_id = _stable_id("catalog-asset-observation", asdict(asset))
    values: tuple[tuple[str, object], ...] = (
        ("identity_status", asset.identity_status),
        ("proposed_citekey", asset.proposed_citekey),
        ("citekey_status", asset.citekey_status),
        ("asset_sha256", asset.sha256),
        ("asset_byte_size", asset.byte_size),
        ("asset_root_alias", asset.root_alias),
        ("asset_relative_path", asset.relative_path),
        ("asset_status", asset.asset_status),
        ("rights_status", asset.rights_status),
    )
    return tuple(
        StateClaim.observed(
            subject_id=subject_id,
            field=field,
            value=value,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=record_id,
            source_locator=f"catalog-asset/{field}",
        )
        for field, value in values
    )


def processing_state_claims(
    *,
    subject_id: str,
    evidence: ProcessingEvidence,
) -> tuple[StateClaim, ...]:
    if evidence.evidence_record_id is None:
        return ()
    values: tuple[tuple[str, object], ...] = (
        ("ingestion_status", evidence.ingestion_status),
        ("transcript_status", evidence.transcript_status),
        ("ingestion_contract_status", evidence.contract_status),
        ("derivation_audit_status", evidence.derivation_audit_status),
    )
    return tuple(
        StateClaim.observed(
            subject_id=subject_id,
            field=field,
            value=value,
            record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
            authoritative_input_id=evidence.evidence_record_id,
            source_locator=f"ingestion-reference-evidence/{field}",
        )
        for field, value in values
    )


def review_state_claims(
    *,
    subject_id: str,
    context_id: str,
    projection: ReviewProjection,
) -> tuple[StateClaim, ...]:
    current_human = set(projection.current_human_decision_ids)
    current_technical = set(projection.current_technical_record_ids)
    claims: list[StateClaim] = []
    for decision in projection.human_decision_history:
        if (
            decision.decision_id not in current_human
            or decision.subject_id != subject_id
            or decision.context_id != context_id
        ):
            continue
        field, owner = {
            HumanReviewDimension.READING: (
                "reading_decision",
                "projectkoios-references",
            ),
            HumanReviewDimension.REVIEW_COLLECTION_INCLUSION: (
                "collection_inclusion",
                "projectkoios-references",
            ),
            HumanReviewDimension.CLAIM_SUPPORT_CHECK: (
                "claim_support_check",
                "owning-research-repository",
            ),
        }[decision.dimension]
        claims.append(
            _make_state_claim(
                subject_id=subject_id,
                field=field,
                knowledge=StateKnowledge.OBSERVED,
                value_json=_canonical_value(decision.decision),
                record_kind=StateRecordKind.HUMAN_DECISION,
                authoritative_input_id=decision.decision_id,
                source_locator=f"review-decision/{decision.dimension.value}",
                authority_owner=owner,
                actor_id=decision.actor.actor_id,
                authority_scope=decision.actor.authority_scope.value,
                actor_verification_record_id=(
                    decision.actor.verification_record_id
                ),
            )
        )
    for record in projection.technical_history:
        if (
            record.record_id in current_technical
            and record.subject_id == subject_id
            and record.context_id == context_id
        ):
            claims.append(
                StateClaim.observed(
                    subject_id=subject_id,
                    field="technical_review_status",
                    value={
                        "kind": record.technical_kind.value,
                        "outcome": record.outcome.value,
                    },
                    record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                    authoritative_input_id=record.record_id,
                    source_locator=(
                        f"technical-review/{record.technical_kind.value}"
                    ),
                )
            )
    return tuple(claims)


def build_reference_state_projection(
    *,
    candidate: ReferenceCandidate,
    collection_id: str,
    collection_row: CollectionRowEvidence | None = None,
    managed_asset: ManagedPdf | None = None,
    acquisition: AcquisitionProjection | None = None,
    processing: ProcessingEvidence | None = None,
    review: ReviewProjection | None = None,
    coverage: CoverageObservation | None = None,
    catalog_assets: tuple[SourceAssetRecord, ...] = (),
    asset_plan: AssetDiscoveryPlan | None = None,
    citation_status: str | None = None,
    citation_input_id: str | None = None,
) -> ReferenceStateProjection:
    """Compose one candidate's state from exact, separately owned inputs."""
    if not isinstance(candidate, ReferenceCandidate):
        raise TypeError("candidate must be a ReferenceCandidate")
    _bounded(collection_id, field="collection_id")
    claims = list(candidate_state_claims(candidate))
    exclusions: list[str] = [
        "canonical identity requires a separate curator decision",
        "scientific support is not projected by references",
        "manuscript use is not projected by references",
        "publication is not projected by references",
        "contract acceptance is not projected by references",
    ]
    if collection_row is not None:
        row_id = collection_row.observation_id or _stable_id(
            "collection-row-observation",
            {
                "collection_id": collection_id,
                "proposed_citekey": candidate.proposed_citekey,
                "row": collection_row,
                "provenance_status": "caller-supplied-normalized-row",
            },
        )
        claims.extend(
            collection_state_claims(
                subject_id=candidate.candidate_id,
                row=collection_row,
                authoritative_input_id=row_id,
            )
        )
    else:
        exclusions.append("collection row evidence was not supplied")
    if managed_asset is not None:
        claims.extend(
            managed_asset_state_claims(
                subject_id=candidate.candidate_id,
                asset=managed_asset,
            )
        )
    else:
        exclusions.append("managed asset evidence was not supplied")
    if acquisition is not None:
        if acquisition.proposed_citekey != candidate.proposed_citekey:
            raise StateProjectionError(
                "acquisition citekey differs from candidate projection"
            )
        claims.extend(
            acquisition_state_claims(
                subject_id=candidate.candidate_id,
                projection=acquisition,
            )
        )
    else:
        exclusions.append("acquisition evidence was not supplied")
    if processing is not None and processing.evidence_record_id is not None:
        claims.extend(
            processing_state_claims(
                subject_id=candidate.candidate_id,
                evidence=processing,
            )
        )
    else:
        exclusions.append("ingestion evidence was not supplied")
    if review is not None:
        claims.extend(
            review_state_claims(
                subject_id=candidate.candidate_id,
                context_id=collection_id,
                projection=review,
            )
        )
    else:
        exclusions.append("review evidence was not supplied")
    if coverage is not None:
        claims.extend(
            coverage_state_claims(
                subject_id=candidate.candidate_id,
                proposed_citekey=candidate.proposed_citekey,
                observation=coverage,
            )
        )
    else:
        exclusions.append("coverage evidence was not supplied")
    if any(not isinstance(item, SourceAssetRecord) for item in catalog_assets):
        raise StateProjectionError(
            "catalog_assets must contain SourceAssetRecord values"
        )
    for asset in catalog_assets:
        if asset.candidate_id != candidate.candidate_id:
            raise StateProjectionError(
                "catalog asset candidate differs from state subject"
            )
        claims.extend(
            catalog_asset_state_claims(
                subject_id=candidate.candidate_id,
                asset=asset,
            )
        )
    if not catalog_assets:
        exclusions.append("catalog asset evidence was not supplied")
    if asset_plan is not None:
        matching_assets = tuple(
            item
            for item in asset_plan.candidates
            if item.candidate_id == candidate.candidate_id
        )
        for asset_candidate in matching_assets:
            claims.extend(
                asset_candidate_state_claims(
                    subject_id=candidate.candidate_id,
                    candidate=asset_candidate,
                    plan=asset_plan,
                )
            )
        if not matching_assets:
            exclusions.append(
                "asset discovery plan contained no matching candidate"
            )
    else:
        exclusions.append("asset discovery plan was not supplied")
    if citation_status is not None:
        if citation_input_id is None:
            raise StateProjectionError(
                "citation status requires an authoritative input identity"
            )
        claims.append(
            StateClaim.observed(
                subject_id=candidate.candidate_id,
                field="citation_status",
                value=citation_status,
                record_kind=StateRecordKind.IMMUTABLE_OBSERVATION,
                authoritative_input_id=citation_input_id,
                source_locator="citation-closure/status",
            )
        )
    elif citation_input_id is not None:
        raise StateProjectionError(
            "citation input identity was supplied without a status"
        )
    else:
        exclusions.append("citation closure evidence was not supplied")
    input_ids = tuple(
        sorted(
            {candidate.candidate_id}
            | {item.authoritative_input_id for item in claims}
        )
    )
    return replay_reference_state(
        subject_id=candidate.candidate_id,
        claims=tuple(claims),
        authoritative_input_ids=input_ids,
        exclusions=tuple(exclusions),
    )


def projection_to_csv(projection: ReferenceStateProjection) -> str:
    """Emit a deterministic, provenance-complete claim-level CSV view."""
    restored = ReferenceStateProjection.from_json(projection.to_json())
    stream = io.StringIO(newline="")
    fields = (
        "schema_version",
        "artifact_kind",
        "generator_name",
        "generator_version",
        "configuration_id",
        "exact_replay",
        "projection_id",
        "subject_id",
        "authoritative_input_ids_json",
        "exclusions_json",
        "field",
        "dimension",
        "authority_owner",
        "resolution",
        "knowledge",
        "value_json",
        "value_authoritative_input_ids_json",
        "record_kinds_json",
        "source_locators_json",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    first_row = True
    for field_value in restored.fields:
        values: tuple[ProjectedValue | None, ...] = (
            field_value.values if field_value.values else (None,)
        )
        for value in values:
            writer.writerow(
                {
                    "schema_version": (
                        restored.schema_version if first_row else ""
                    ),
                    "artifact_kind": (
                        restored.artifact_kind if first_row else ""
                    ),
                    "generator_name": (
                        restored.generator_name if first_row else ""
                    ),
                    "generator_version": (
                        restored.generator_version if first_row else ""
                    ),
                    "configuration_id": (
                        restored.configuration_id if first_row else ""
                    ),
                    "exact_replay": (
                        str(restored.exact_replay).lower() if first_row else ""
                    ),
                    "projection_id": restored.projection_id
                    if first_row
                    else "",
                    "subject_id": restored.subject_id if first_row else "",
                    "authoritative_input_ids_json": (
                        _canonical_value(restored.authoritative_input_ids)
                        if first_row
                        else ""
                    ),
                    "exclusions_json": (
                        _canonical_value(restored.exclusions)
                        if first_row
                        else ""
                    ),
                    "field": field_value.field,
                    "dimension": field_value.dimension.value,
                    "authority_owner": field_value.authority_owner,
                    "resolution": field_value.resolution.value,
                    "knowledge": "" if value is None else value.knowledge.value,
                    "value_json": ""
                    if value is None
                    else (value.value_json or ""),
                    "value_authoritative_input_ids_json": (
                        ""
                        if value is None
                        else _canonical_value(value.authoritative_input_ids)
                    ),
                    "record_kinds_json": (
                        ""
                        if value is None
                        else _canonical_value(
                            tuple(item.value for item in value.record_kinds)
                        )
                    ),
                    "source_locators_json": (
                        ""
                        if value is None
                        else _canonical_value(value.source_locators)
                    ),
                }
            )
            first_row = False
    result = stream.getvalue()
    if len(result.encode("utf-8")) > _MAX_PROJECTION_CSV_BYTES:
        raise StateProjectionError(
            "state projection CSV exceeds its byte limit"
        )
    return result


def projection_from_csv(text: str) -> ReferenceStateProjection:
    """Strictly parse the deterministic CSV projection and verify its ID."""
    if (
        not isinstance(text, str)
        or len(text.encode("utf-8")) > _MAX_PROJECTION_CSV_BYTES
    ):
        raise StateProjectionError(
            "state projection CSV exceeds its byte limit"
        )
    try:
        with bounded_csv_field_size(_MAX_PROJECTION_CSV_FIELD_CHARACTERS):
            rows = tuple(
                csv.DictReader(io.StringIO(text, newline=""), strict=True)
            )
    except csv.Error as error:
        raise StateProjectionError(
            "state projection CSV is malformed"
        ) from error
    if not rows or len(rows) > len(STATE_FIELD_RULES) + _MAX_CLAIMS:
        raise StateProjectionError("state projection CSV row count is invalid")
    required = {
        "schema_version",
        "artifact_kind",
        "generator_name",
        "generator_version",
        "configuration_id",
        "exact_replay",
        "projection_id",
        "subject_id",
        "authoritative_input_ids_json",
        "exclusions_json",
        "field",
        "dimension",
        "authority_owner",
        "resolution",
        "knowledge",
        "value_json",
        "value_authoritative_input_ids_json",
        "record_kinds_json",
        "source_locators_json",
    }
    if set(rows[0]) != required or any(set(row) != required for row in rows):
        raise StateProjectionError("state projection CSV columns are invalid")
    metadata = {
        key: rows[0][key]
        for key in (
            "schema_version",
            "artifact_kind",
            "generator_name",
            "generator_version",
            "configuration_id",
            "exact_replay",
            "projection_id",
            "subject_id",
            "authoritative_input_ids_json",
            "exclusions_json",
        )
    }
    if any(any(row[key] for key in metadata) for row in rows[1:]):
        raise StateProjectionError(
            "state projection CSV metadata must occur only in its first row"
        )
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["field"], []).append(row)
    fields: list[ProjectedField] = []
    for name in sorted(STATE_FIELD_RULES):
        field_rows = grouped.get(name)
        if not field_rows:
            raise StateProjectionError(f"state projection CSV omits {name}")
        first = field_rows[0]
        for key in ("dimension", "authority_owner", "resolution"):
            if any(row[key] != first[key] for row in field_rows):
                raise StateProjectionError(
                    f"state projection CSV {name} differs"
                )
        values: list[ProjectedValue] = []
        for row in field_rows:
            if not row["knowledge"]:
                if len(field_rows) != 1 or any(
                    row[key]
                    for key in (
                        "value_json",
                        "value_authoritative_input_ids_json",
                        "record_kinds_json",
                        "source_locators_json",
                    )
                ):
                    raise StateProjectionError(
                        "empty projected field row is invalid"
                    )
                continue
            value_ids = _json_string_tuple(
                row["value_authoritative_input_ids_json"],
                field="value_authoritative_input_ids_json",
            )
            kinds = tuple(
                _enum(StateRecordKind, item, field="record_kind")
                for item in _json_string_tuple(
                    row["record_kinds_json"], field="record_kinds_json"
                )
            )
            values.append(
                ProjectedValue(
                    knowledge=_enum(
                        StateKnowledge, row["knowledge"], field="knowledge"
                    ),
                    value_json=row["value_json"] or None,
                    authoritative_input_ids=value_ids,
                    record_kinds=kinds,
                    source_locators=_json_string_tuple(
                        row["source_locators_json"],
                        field="source_locators_json",
                    ),
                )
            )
        fields.append(
            ProjectedField(
                field=name,
                dimension=_enum(
                    StateDimension, first["dimension"], field="dimension"
                ),
                authority_owner=first["authority_owner"],
                resolution=_enum(
                    StateResolution, first["resolution"], field="resolution"
                ),
                values=tuple(values),
            )
        )
    try:
        schema_version = int(metadata["schema_version"])
    except ValueError as error:
        raise StateProjectionError(
            "state projection CSV schema_version is invalid"
        ) from error
    projection = _make_projection(
        schema_version=schema_version,
        artifact_kind=metadata["artifact_kind"],
        generator_name=metadata["generator_name"],
        generator_version=metadata["generator_version"],
        configuration_id=metadata["configuration_id"],
        subject_id=metadata["subject_id"],
        authoritative_input_ids=_json_string_tuple(
            metadata["authoritative_input_ids_json"],
            field="authoritative_input_ids_json",
        ),
        fields=tuple(fields),
        exclusions=_json_string_tuple(
            metadata["exclusions_json"], field="exclusions_json"
        ),
        exact_replay=(metadata["exact_replay"] == "true"),
        projection_id=metadata["projection_id"],
    )
    if projection_to_csv(projection) != text:
        raise StateProjectionError("state projection CSV is noncanonical")
    return projection


def projection_to_biblatex(projection: ReferenceStateProjection) -> str:
    """Emit a deterministic non-authoritative bibliographic view.

    Discrepant fields are omitted rather than selected. Reimporting these bytes
    through the bibliography adapter creates a new source observation; it never
    mutates this projection's inputs.
    """
    values: dict[str, object] = {}
    discrepant: list[str] = []
    for field in projection.fields:
        if field.resolution is StateResolution.DISCREPANCY:
            discrepant.append(field.field)
        elif (
            len(field.values) == 1
            and field.values[0].knowledge is StateKnowledge.OBSERVED
        ):
            values[field.field] = field.values[0].value()
    citekey = values.get("proposed_citekey")
    entry_type = values.get("entry_type", "misc")
    if not isinstance(citekey, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:+-]*", citekey
    ):
        raise StateProjectionError(
            "BibLaTeX projection requires one safe citekey"
        )
    if not isinstance(entry_type, str) or not re.fullmatch(
        r"[A-Za-z]+", entry_type
    ):
        raise StateProjectionError("BibLaTeX projection entry type is invalid")
    fields: list[tuple[str, str]] = []
    for source, target in (
        ("title", "title"),
        ("year", "year"),
        ("doi", "doi"),
        ("isbn", "isbn"),
        ("url", "url"),
        ("eprint", "eprint"),
    ):
        value = values.get(source)
        if isinstance(value, str):
            fields.append((target, value))
    authors = values.get("authors")
    if isinstance(authors, list) and all(
        isinstance(item, str) for item in authors
    ):
        fields.append(("author", " and ".join(authors)))
    fields.extend(
        (
            ("x-projectkoios-projection-id", projection.projection_id),
            (
                "x-projectkoios-authoritative-inputs",
                ";".join(projection.authoritative_input_ids),
            ),
            ("x-projectkoios-discrepancies", ";".join(discrepant)),
            ("x-projectkoios-authority", "non-authoritative-projection"),
        )
    )
    rendered = ",\n".join(
        f"  {name} = {{{_bib_escape(value)}}}" for name, value in fields
    )
    return f"@{entry_type}{{{citekey},\n{rendered}\n}}\n"


def _make_state_claim(**values: object) -> StateClaim:
    claim = object.__new__(StateClaim)
    for name, value in values.items():
        object.__setattr__(claim, name, value)
    claim.__post_init__()
    return claim


def _resolution(values: tuple[ProjectedValue, ...]) -> StateResolution:
    if not values:
        return StateResolution.NOT_OBSERVED
    if len(values) > 1:
        return StateResolution.DISCREPANCY
    return (
        StateResolution.AGREEMENT
        if len(values[0].authoritative_input_ids) > 1
        else StateResolution.SINGLE
    )


def _make_projection(**values: object) -> ReferenceStateProjection:
    projection = object.__new__(ReferenceStateProjection)
    for name, value in values.items():
        object.__setattr__(projection, name, value)
    projection.__post_init__()
    return projection


def _validate_state_value(field: str, value: object) -> None:
    if field in _EXACT_FIELD_VALUES:
        if (
            not isinstance(value, str)
            or value not in _EXACT_FIELD_VALUES[field]
        ):
            raise StateProjectionError(f"{field} value is unsupported")
        return
    if field in _STRING_FIELDS:
        text = _bounded(value, field=f"{field} value")
        if (
            field == "proposed_citekey"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+-]*", text) is None
        ):
            raise StateProjectionError("proposed_citekey value is invalid")
        if field in {"asset_root_alias", "asset_relative_path"}:
            _safe_locator(text)
        return
    if field in _STRING_ARRAY_FIELDS:
        if (
            not isinstance(value, list)
            or len(value) > _MAX_CLAIMS
            or any(not isinstance(item, str) for item in value)
        ):
            raise StateProjectionError(f"{field} value must be a string array")
        asset_observation_fields = {
            "asset_competing_observation_ids",
            "asset_alternate_version_observation_ids",
        }
        if field in asset_observation_fields and value != sorted(set(value)):
            raise StateProjectionError(
                f"{field} value must be sorted and unique"
            )
        for item in value:
            _bounded(item, field=f"{field} item")
            if field in asset_observation_fields and (
                re.fullmatch(
                    r"asset-heuristic-observation:sha256:[0-9a-f]{64}",
                    item,
                )
                is None
            ):
                raise StateProjectionError(
                    f"{field} item must be an asset observation identity"
                )
        return
    if field == "candidate_id":
        _content_id(value, field="candidate_id value")
        return
    if field == "asset_sha256":
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
        ):
            raise StateProjectionError("asset_sha256 value is invalid")
        return
    if field == "asset_byte_size":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise StateProjectionError(
                "asset_byte_size value must be a positive integer"
            )
        return
    if field == "asset_heuristic_observations":
        if not isinstance(value, list) or not value or len(value) > 32:
            raise StateProjectionError(
                "asset_heuristic_observations value is invalid"
            )
        try:
            parsed = tuple(
                AssetHeuristicObservation.from_dict(item) for item in value
            )
        except (TypeError, ValueError) as error:
            raise StateProjectionError(
                "asset_heuristic_observations item is invalid"
            ) from error
        if parsed != tuple(
            sorted(
                parsed,
                key=lambda item: (
                    item.kind.value,
                    item.matched_tokens,
                    item.compared_token_count,
                ),
            )
        ):
            raise StateProjectionError(
                "asset_heuristic_observations must be sorted"
            )
        return
    if field == "technical_review_status":
        if (
            not isinstance(value, dict)
            or set(value) != {"kind", "outcome"}
            or any(not isinstance(item, str) for item in value.values())
        ):
            raise StateProjectionError(
                "technical_review_status value is invalid"
            )
        _bounded(value["kind"], field="technical review kind")
        _bounded(value["outcome"], field="technical review outcome")
        return
    raise StateProjectionError(f"{field} has no value contract")


def _bounded_csv_projection_field(value: object, *, field: str) -> None:
    if len(_canonical_value(value)) > _MAX_PROJECTION_CSV_FIELD_CHARACTERS:
        raise StateProjectionError(f"{field} exceeds the CSV field limit")


def _canonical_value(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as error:
        raise StateProjectionError(
            "state value is not canonical JSON"
        ) from error


def _parse_canonical_value(
    text: str, *, max_bytes: int = _MAX_VALUE_BYTES
) -> object:
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise StateProjectionError("state value exceeds its byte limit")
    try:
        value = json.loads(text, parse_constant=_raise_nonfinite)
    except (json.JSONDecodeError, RecursionError) as error:
        raise StateProjectionError("state value JSON is invalid") from error
    if _canonical_value(value) != text:
        raise StateProjectionError("state value JSON is not canonical")
    return value


def _pretty_json(value: object) -> str:
    return (
        json.dumps(
            value,
            allow_nan=False,
            default=_json_default,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _raise_nonfinite(value: str) -> object:
    raise StateProjectionError(f"non-finite JSON value is unsupported: {value}")


def _json_default(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return asdict(cast("Any", value))
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _stable_id(kind: str, value: object) -> str:
    content = _canonical_value(value).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(content).hexdigest()}"


def _content_id(value: object, *, field: str) -> None:
    if not isinstance(value, str) or _CONTENT_ID.fullmatch(value) is None:
        raise StateProjectionError(f"{field} must be a content identity")


def _ordered_unique_content_ids(values: object, *, field: str) -> None:
    if not isinstance(values, tuple):
        raise StateProjectionError(f"{field} must be a tuple")
    if tuple(sorted(set(values))) != values:
        raise StateProjectionError(f"{field} must be sorted and unique")
    for value in values:
        _content_id(value, field=field)


def _safe_locator(value: object) -> str:
    locator = _bounded(value, field="source locator")
    if (
        locator.startswith(("/", "~"))
        or "\\" in locator
        or re.match(r"^[A-Za-z]:/", locator) is not None
        or any(part == ".." for part in locator.split("/"))
    ):
        raise StateProjectionError(
            "source locator must not expose an absolute or traversing path"
        )
    return locator


def _bounded(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_TEXT
    ):
        raise StateProjectionError(f"{field} must be bounded non-empty text")
    return value


def _string(value: object, *, field: str) -> str:
    return _bounded(value, field=field)


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _strings(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_CLAIMS:
        raise StateProjectionError(f"{field} must be a bounded string array")
    return tuple(_string(item, field=field) for item in value)


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateProjectionError(f"{field} must be an integer")
    return value


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise StateProjectionError(f"{field} must be Boolean")
    return value


def _enum[EnumValue: StrEnum](
    enum_type: type[EnumValue], value: object, *, field: str
) -> EnumValue:
    if not isinstance(value, str):
        raise StateProjectionError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise StateProjectionError(f"{field} is unsupported") from error


def _json_string_tuple(text: str, *, field: str) -> tuple[str, ...]:
    value = _parse_canonical_value(
        text,
        max_bytes=_MAX_PROJECTION_BYTES,
    )
    if (
        not isinstance(value, list)
        or len(value) > _MAX_CLAIMS
        or any(not isinstance(item, str) for item in value)
    ):
        raise StateProjectionError(f"{field} must encode a string array")
    return cast(tuple[str, ...], tuple(value))


def _bib_escape(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise StateProjectionError("BibLaTeX projection value is unsafe")
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
