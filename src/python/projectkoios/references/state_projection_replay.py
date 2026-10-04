from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import islice

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.state_projection import (
    STATE_FIELD_RULES,
    STATE_PROJECTION_ARTIFACT_KIND,
    STATE_PROJECTION_CONFIGURATION_ID,
    STATE_PROJECTION_GENERATOR,
    STATE_PROJECTION_GENERATOR_VERSION,
    STATE_PROJECTION_MAX_BYTES,
    STATE_PROJECTION_MAX_CLAIMS,
    STATE_PROJECTION_MAX_EXCLUSIONS,
    STATE_PROJECTION_MAX_INPUTS,
    STATE_PROJECTION_SCHEMA_VERSION,
    ProjectedField,
    ProjectedValue,
    ReferenceStateProjection,
    StateClaim,
    StateKnowledge,
    StateProjectionError,
    StateResolution,
)

type JsonValue = (
    None
    | bool
    | int
    | str
    | list[JsonValue]
    | tuple[JsonValue, ...]
    | dict[str, JsonValue]
)

_CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceStateReplayRequest(DataObjectActionRequest):
    """Request deterministic reduction of one bounded state-claim set."""

    subject_id: str
    claims: tuple[StateClaim, ...]
    authoritative_input_ids: tuple[str, ...]
    exclusions: tuple[str, ...] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        self._validate_content_id(self.subject_id, field_name="subject_id")
        if not isinstance(self.claims, tuple) or any(
            not isinstance(claim, StateClaim) for claim in self.claims
        ):
            raise TypeError("claims must be a StateClaim tuple")
        if len(self.claims) > STATE_PROJECTION_MAX_CLAIMS:
            raise StateProjectionError("state claims exceed the record limit")
        if not isinstance(self.authoritative_input_ids, tuple) or any(
            not isinstance(input_id, str)
            for input_id in self.authoritative_input_ids
        ):
            raise TypeError("authoritative_input_ids must be a string tuple")
        if len(self.authoritative_input_ids) > STATE_PROJECTION_MAX_INPUTS:
            raise StateProjectionError(
                "state projection inputs exceed the record limit"
            )
        if not isinstance(self.exclusions, tuple) or any(
            not isinstance(exclusion, str) for exclusion in self.exclusions
        ):
            raise TypeError("exclusions must be a string tuple")
        if len(self.exclusions) > STATE_PROJECTION_MAX_EXCLUSIONS:
            raise StateProjectionError(
                "state projection exclusions exceed the record limit"
            )
        object.__setattr__(self, "request_id", self._identity())

    @classmethod
    def from_iterables(
        cls,
        *,
        subject_id: str,
        claims: Iterable[StateClaim],
        authoritative_input_ids: Iterable[str],
        exclusions: Iterable[str] = (),
    ) -> ReferenceStateReplayRequest:
        claim_values = tuple(
            islice(iter(claims), STATE_PROJECTION_MAX_CLAIMS + 1)
        )
        if len(claim_values) > STATE_PROJECTION_MAX_CLAIMS:
            raise StateProjectionError("state claims exceed the record limit")
        input_values = tuple(
            islice(
                iter(authoritative_input_ids),
                STATE_PROJECTION_MAX_INPUTS + 1,
            )
        )
        if len(input_values) > STATE_PROJECTION_MAX_INPUTS:
            raise StateProjectionError(
                "state projection inputs exceed the record limit"
            )
        exclusion_values = tuple(
            islice(iter(exclusions), STATE_PROJECTION_MAX_EXCLUSIONS + 1)
        )
        if len(exclusion_values) > STATE_PROJECTION_MAX_EXCLUSIONS:
            raise StateProjectionError(
                "state projection exclusions exceed the record limit"
            )
        return cls(
            subject_id=subject_id,
            claims=claim_values,
            authoritative_input_ids=input_values,
            exclusions=exclusion_values,
        )

    def _identity(self) -> str:
        claims: list[JsonValue] = [
            {
                "actor_id": claim.actor_id,
                "actor_verification_record_id": (
                    claim.actor_verification_record_id
                ),
                "authoritative_input_id": claim.authoritative_input_id,
                "authority_owner": claim.authority_owner,
                "authority_scope": claim.authority_scope,
                "field": claim.field,
                "knowledge": claim.knowledge.value,
                "record_kind": claim.record_kind.value,
                "source_locator": claim.source_locator,
                "subject_id": claim.subject_id,
                "value_json": claim.value_json,
            }
            for claim in self.claims
        ]
        payload: JsonValue = {
            "authoritative_input_ids": self.authoritative_input_ids,
            "claims": claims,
            "exclusions": self.exclusions,
            "subject_id": self.subject_id,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "reference-state-replay-request:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )

    @staticmethod
    def _validate_content_id(value: str, *, field_name: str) -> None:
        if _CONTENT_ID.fullmatch(value) is None:
            raise StateProjectionError(
                f"{field_name} must be a content identity"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceStateReplayResult(DataObjectActionResult):
    """Bind one replay request to its deterministic state projection."""

    request: ReferenceStateReplayRequest
    projection: ReferenceStateProjection
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not ReferenceStateReplayRequest:
            raise TypeError("request must be a ReferenceStateReplayRequest")
        if type(self.projection) is not ReferenceStateProjection:
            raise TypeError("projection must be a ReferenceStateProjection")
        if self.projection.subject_id != self.request.subject_id:
            raise StateProjectionError(
                "replay result subject differs from its request"
            )
        requested_inputs = tuple(
            sorted(set(self.request.authoritative_input_ids))
        )
        if self.projection.authoritative_input_ids != requested_inputs:
            raise StateProjectionError(
                "replay result inputs differ from its request"
            )
        canonical = json.dumps(
            {
                "projection_id": self.projection.projection_id,
                "request_id": self.request.request_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        object.__setattr__(
            self,
            "result_id",
            "reference-state-replay-result:sha256:"
            + hashlib.sha256(canonical).hexdigest(),
        )


class ReferenceStateReplayer(
    DataObjectActionizer[
        ReferenceStateReplayRequest,
        ReferenceStateReplayResult,
    ]
):
    """Reduce exact state claims without selecting a preferred source."""

    __slots__ = ()

    def action(
        self,
        *,
        request: ReferenceStateReplayRequest,
    ) -> ReferenceStateReplayResult:
        return self.replay(request=request)

    def replay(
        self,
        *,
        request: ReferenceStateReplayRequest,
    ) -> ReferenceStateReplayResult:
        if type(request) is not ReferenceStateReplayRequest:
            raise TypeError("request must be a ReferenceStateReplayRequest")
        if any(
            claim.subject_id != request.subject_id for claim in request.claims
        ):
            raise StateProjectionError(
                "state claim subject differs from projection"
            )
        input_ids = tuple(sorted(set(request.authoritative_input_ids)))
        self._validate_input_ids(input_ids)
        if not input_ids:
            raise StateProjectionError(
                "state projection requires authoritative inputs"
            )
        undeclared = {
            claim.authoritative_input_id for claim in request.claims
        } - set(input_ids)
        if undeclared:
            raise StateProjectionError(
                f"state claims cite undeclared inputs: {sorted(undeclared)}"
            )

        grouped: dict[str, list[StateClaim]] = {
            name: [] for name in STATE_FIELD_RULES
        }
        for claim in request.claims:
            grouped[claim.field].append(claim)
        fields = tuple(
            self._project_field(name=name, claims=grouped[name])
            for name in sorted(STATE_FIELD_RULES)
        )
        exclusions = tuple(sorted(set(request.exclusions)))
        projection_id = self._projection_identity(
            subject_id=request.subject_id,
            authoritative_input_ids=input_ids,
            fields=fields,
            exclusions=exclusions,
        )
        projection = ReferenceStateProjection(
            schema_version=STATE_PROJECTION_SCHEMA_VERSION,
            artifact_kind=STATE_PROJECTION_ARTIFACT_KIND,
            generator_name=STATE_PROJECTION_GENERATOR,
            generator_version=STATE_PROJECTION_GENERATOR_VERSION,
            configuration_id=STATE_PROJECTION_CONFIGURATION_ID,
            subject_id=request.subject_id,
            authoritative_input_ids=input_ids,
            fields=fields,
            exclusions=exclusions,
            exact_replay=True,
            projection_id=projection_id,
        )
        if (
            len(projection.to_json().encode("utf-8"))
            > STATE_PROJECTION_MAX_BYTES
        ):
            raise StateProjectionError(
                "state projection exceeds its aggregate byte limit"
            )
        return ReferenceStateReplayResult(
            request=request,
            projection=projection,
        )

    def _project_field(
        self,
        *,
        name: str,
        claims: list[StateClaim],
    ) -> ProjectedField:
        rule = STATE_FIELD_RULES[name]
        grouped: dict[tuple[StateKnowledge, str | None], list[StateClaim]] = {}
        for claim in claims:
            grouped.setdefault((claim.knowledge, claim.value_json), []).append(
                claim
            )
        values = tuple(
            ProjectedValue(
                knowledge=knowledge,
                value_json=value_json,
                authoritative_input_ids=tuple(
                    sorted({claim.authoritative_input_id for claim in items})
                ),
                record_kinds=tuple(
                    sorted({claim.record_kind for claim in items}, key=str)
                ),
                source_locators=tuple(
                    sorted({claim.source_locator for claim in items})
                ),
            )
            for (knowledge, value_json), items in sorted(
                grouped.items(),
                key=lambda item: (item[0][0].value, item[0][1] or ""),
            )
        )
        return ProjectedField(
            field=name,
            dimension=rule.dimension,
            authority_owner=rule.authority_owner,
            resolution=self._resolution(values),
            values=values,
        )

    @staticmethod
    def _resolution(values: tuple[ProjectedValue, ...]) -> StateResolution:
        if not values:
            return StateResolution.NOT_OBSERVED
        if len(values) > 1:
            return StateResolution.DISCREPANCY
        if len(values[0].authoritative_input_ids) > 1:
            return StateResolution.AGREEMENT
        return StateResolution.SINGLE

    @staticmethod
    def _validate_input_ids(values: tuple[str, ...]) -> None:
        if values != tuple(sorted(set(values))):
            raise StateProjectionError(
                "authoritative_input_ids must be sorted and unique"
            )
        for value in values:
            ReferenceStateReplayRequest._validate_content_id(
                value,
                field_name="authoritative_input_ids",
            )

    @staticmethod
    def _projection_identity(
        *,
        subject_id: str,
        authoritative_input_ids: tuple[str, ...],
        fields: tuple[ProjectedField, ...],
        exclusions: tuple[str, ...],
    ) -> str:
        serialized_fields: list[JsonValue] = []
        for projected_field in fields:
            serialized_values: list[JsonValue] = [
                {
                    "authoritative_input_ids": value.authoritative_input_ids,
                    "knowledge": value.knowledge.value,
                    "record_kinds": tuple(
                        kind.value for kind in value.record_kinds
                    ),
                    "source_locators": value.source_locators,
                    "value_json": value.value_json,
                }
                for value in projected_field.values
            ]
            serialized_fields.append(
                {
                    "authority_owner": projected_field.authority_owner,
                    "dimension": projected_field.dimension.value,
                    "field": projected_field.field,
                    "resolution": projected_field.resolution.value,
                    "values": serialized_values,
                }
            )
        payload: JsonValue = {
            "artifact_kind": STATE_PROJECTION_ARTIFACT_KIND,
            "authoritative_input_ids": authoritative_input_ids,
            "configuration_id": STATE_PROJECTION_CONFIGURATION_ID,
            "exact_replay": True,
            "exclusions": exclusions,
            "fields": serialized_fields,
            "generator_name": STATE_PROJECTION_GENERATOR,
            "generator_version": STATE_PROJECTION_GENERATOR_VERSION,
            "schema_version": STATE_PROJECTION_SCHEMA_VERSION,
            "subject_id": subject_id,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "reference-state-projection:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )
