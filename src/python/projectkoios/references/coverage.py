from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Self, cast

from projectkoios.references.io_limits import (
    RECONCILIATION_IO_LIMITS,
    validate_json_text_nesting,
)
from projectkoios.references.path_safety import (
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

_MAX_COVERAGE_REFERENCES = 10_000
_MAX_CANDIDATES_PER_REFERENCE = 256
_MAX_TEXT = 4096
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CoverageState(StrEnum):
    NOT_STARTED = "not-started"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class AmbiguityEvaluation(StrEnum):
    EVALUATED = "evaluated"
    NOT_EVALUATED = "not-evaluated"


class CandidateVersionRelation(StrEnum):
    PRIMARY_OR_UNKNOWN = "primary-or-unknown"
    ALTERNATE = "alternate"


class CoverageAccessState(StrEnum):
    NONE = "none"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    ACCESS_CONTROLLED = "access-controlled"
    FULL_TEXT_NOT_PUBLIC = "full-text-not-public"


@dataclass(frozen=True)
class CoverageCandidate:
    root_alias: str
    relative_path: str
    sha256: str
    byte_size: int
    version_relation: CandidateVersionRelation

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if (
            not isinstance(self.sha256, str)
            or _SHA256.fullmatch(self.sha256) is None
        ):
            raise ValueError("coverage candidate SHA-256 must be lowercase hex")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("coverage candidate byte size must be positive")
        if not isinstance(self.version_relation, CandidateVersionRelation):
            raise ValueError("unsupported candidate version relation")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "root_alias",
                "relative_path",
                "sha256",
                "byte_size",
                "version_relation",
            },
            label="coverage candidate",
        )
        if not all(
            isinstance(data[field], str)
            for field in (
                "root_alias",
                "relative_path",
                "sha256",
                "version_relation",
            )
        ):
            raise ValueError("coverage candidate string fields must be strings")
        if type(data["byte_size"]) is not int:
            raise ValueError("coverage candidate byte_size must be an integer")
        return cls(
            root_alias=cast(str, data["root_alias"]),
            relative_path=cast(str, data["relative_path"]),
            sha256=cast(str, data["sha256"]),
            byte_size=cast(int, data["byte_size"]),
            version_relation=CandidateVersionRelation(
                cast(str, data["version_relation"])
            ),
        )


@dataclass(frozen=True)
class ReferenceCoverage:
    citekey: str
    no_match: bool
    access_state: CoverageAccessState
    candidates: tuple[CoverageCandidate, ...]
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        if type(self.no_match) is not bool:
            raise ValueError("coverage no_match must be a boolean")
        if not isinstance(self.access_state, CoverageAccessState):
            raise ValueError("unsupported coverage access state")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(candidate, CoverageCandidate)
            for candidate in self.candidates
        ):
            raise ValueError("coverage candidates must be a candidate tuple")
        if len(self.candidates) > _MAX_CANDIDATES_PER_REFERENCE:
            raise ValueError("coverage candidates exceed the hard limit")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("coverage evidence must be a non-empty tuple")
        _validate_sorted_strings(self.evidence, field="coverage evidence")
        candidate_keys = tuple(
            (
                item.root_alias,
                item.relative_path,
                item.sha256,
                item.version_relation,
            )
            for item in self.candidates
        )
        if candidate_keys != tuple(sorted(candidate_keys)):
            raise ValueError(
                "coverage candidates must be deterministically sorted"
            )
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("coverage candidates contain duplicates")
        digests_by_location: dict[tuple[str, str], set[str]] = {}
        sizes_by_digest: dict[str, set[int]] = {}
        relations_by_digest: dict[str, set[CandidateVersionRelation]] = {}
        for candidate in self.candidates:
            location = (candidate.root_alias, candidate.relative_path)
            digests_by_location.setdefault(location, set()).add(
                candidate.sha256
            )
            sizes_by_digest.setdefault(candidate.sha256, set()).add(
                candidate.byte_size
            )
            relations_by_digest.setdefault(candidate.sha256, set()).add(
                candidate.version_relation
            )
        if any(len(digests) > 1 for digests in digests_by_location.values()):
            raise ValueError(
                "one candidate location has contradictory content identities"
            )
        if any(len(sizes) > 1 for sizes in sizes_by_digest.values()):
            raise ValueError(
                "one candidate digest has contradictory byte sizes"
            )
        if any(
            len(relations) > 1 for relations in relations_by_digest.values()
        ):
            raise ValueError(
                "one candidate digest has contradictory version relations"
            )
        evidence_kinds = (
            int(self.no_match)
            + bool(self.candidates)
            + (self.access_state is not CoverageAccessState.NONE)
        )
        if evidence_kinds != 1:
            raise ValueError(
                "coverage result must contain exactly one of no-match, "
                "candidates, or access state"
            )

    @property
    def competing_content_count(self) -> int:
        return len(
            {
                item.sha256
                for item in self.candidates
                if item.version_relation
                is CandidateVersionRelation.PRIMARY_OR_UNKNOWN
            }
        )

    @property
    def alternate_content_count(self) -> int:
        return len(
            {
                item.sha256
                for item in self.candidates
                if item.version_relation is CandidateVersionRelation.ALTERNATE
            }
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "citekey",
                "no_match",
                "access_state",
                "candidates",
                "evidence",
            },
            label="reference coverage",
        )
        if not isinstance(data["citekey"], str):
            raise ValueError("coverage citekey must be a string")
        if type(data["no_match"]) is not bool:
            raise ValueError("coverage no_match must be a boolean")
        if not isinstance(data["access_state"], str):
            raise ValueError("coverage access_state must be a string")
        if not isinstance(data["candidates"], list):
            raise ValueError("coverage candidates must be an array")
        evidence = _string_array(data["evidence"], field="coverage evidence")
        return cls(
            citekey=data["citekey"],
            no_match=data["no_match"],
            access_state=CoverageAccessState(data["access_state"]),
            candidates=tuple(
                CoverageCandidate.from_dict(item) for item in data["candidates"]
            ),
            evidence=evidence,
        )


@dataclass(frozen=True)
class CoverageObservation:
    schema_version: int
    asserted_source_revision: str
    state: CoverageState
    authorized_root_aliases: tuple[str, ...]
    exclusions: tuple[str, ...]
    failures: tuple[str, ...]
    ambiguity_evaluation: AmbiguityEvaluation
    references: tuple[ReferenceCoverage, ...]
    coverage_id: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported coverage-observation schema version")
        _bounded_text(
            self.asserted_source_revision,
            field="asserted_source_revision",
        )
        if not isinstance(self.state, CoverageState):
            raise ValueError("unsupported coverage state")
        if not isinstance(self.ambiguity_evaluation, AmbiguityEvaluation):
            raise ValueError("unsupported ambiguity-evaluation state")
        _validate_sorted_strings(
            self.authorized_root_aliases,
            field="authorized root aliases",
        )
        for alias in self.authorized_root_aliases:
            validate_root_alias(alias)
        _validate_sorted_strings(self.exclusions, field="coverage exclusions")
        _validate_sorted_strings(self.failures, field="coverage failures")
        if not isinstance(self.references, tuple) or any(
            not isinstance(item, ReferenceCoverage) for item in self.references
        ):
            raise ValueError("coverage references must be a reference tuple")
        if len(self.references) > _MAX_COVERAGE_REFERENCES:
            raise ValueError("coverage references exceed the hard limit")
        citekeys = tuple(item.citekey for item in self.references)
        if citekeys != tuple(sorted(citekeys)):
            raise ValueError("coverage references must be sorted by citekey")
        if len(citekeys) != len(set(citekeys)):
            raise ValueError("coverage references contain duplicate citekeys")
        aliases = set(self.authorized_root_aliases)
        if any(
            candidate.root_alias not in aliases
            for item in self.references
            for candidate in item.candidates
        ):
            raise ValueError(
                "coverage candidate uses an unauthorized root alias"
            )
        if self.state is CoverageState.NOT_STARTED and (
            self.authorized_root_aliases
            or self.references
            or self.failures
            or self.exclusions
        ):
            raise ValueError(
                "not-started coverage cannot contain scan observations"
            )
        if self.state is not CoverageState.NOT_STARTED and not (
            self.authorized_root_aliases
        ):
            raise ValueError("attempted coverage requires authorized roots")
        if self.state is CoverageState.COMPLETE and self.failures:
            raise ValueError("complete coverage cannot contain failures")
        if self.state is CoverageState.INCOMPLETE and not (
            self.exclusions or self.failures
        ):
            raise ValueError(
                "incomplete coverage requires an exclusion or failure"
            )
        if self.state is CoverageState.FAILED and not self.failures:
            raise ValueError("failed coverage requires failure evidence")
        if (
            self.ambiguity_evaluation is AmbiguityEvaluation.NOT_EVALUATED
            and any(
                item.competing_content_count > 1 for item in self.references
            )
        ):
            raise ValueError("competing candidates require evaluated ambiguity")
        expected_id = self.identity_for(
            schema_version=self.schema_version,
            asserted_source_revision=self.asserted_source_revision,
            state=self.state,
            authorized_root_aliases=self.authorized_root_aliases,
            exclusions=self.exclusions,
            failures=self.failures,
            ambiguity_evaluation=self.ambiguity_evaluation,
            references=self.references,
        )
        if self.coverage_id != expected_id:
            raise ValueError("coverage observation identity does not match")

    @classmethod
    def create(
        cls,
        *,
        asserted_source_revision: str,
        state: CoverageState,
        authorized_root_aliases: tuple[str, ...],
        exclusions: tuple[str, ...],
        failures: tuple[str, ...],
        ambiguity_evaluation: AmbiguityEvaluation,
        references: tuple[ReferenceCoverage, ...],
    ) -> Self:
        coverage_id = cls.identity_for(
            schema_version=1,
            asserted_source_revision=asserted_source_revision,
            state=state,
            authorized_root_aliases=authorized_root_aliases,
            exclusions=exclusions,
            failures=failures,
            ambiguity_evaluation=ambiguity_evaluation,
            references=references,
        )
        return cls(
            schema_version=1,
            asserted_source_revision=asserted_source_revision,
            state=state,
            authorized_root_aliases=authorized_root_aliases,
            exclusions=exclusions,
            failures=failures,
            ambiguity_evaluation=ambiguity_evaluation,
            references=references,
            coverage_id=coverage_id,
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        validate_json_text_nesting(
            text,
            limits=RECONCILIATION_IO_LIMITS,
            resource="coverage observation JSON",
        )
        value = json.loads(text)
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "asserted_source_revision",
                "state",
                "authorized_root_aliases",
                "exclusions",
                "failures",
                "ambiguity_evaluation",
                "references",
                "coverage_id",
            },
            label="coverage observation",
        )
        if type(data["schema_version"]) is not int:
            raise ValueError("coverage schema_version must be an integer")
        for field in (
            "asserted_source_revision",
            "state",
            "ambiguity_evaluation",
            "coverage_id",
        ):
            if not isinstance(data[field], str):
                raise ValueError(f"coverage {field} must be a string")
        if not isinstance(data["references"], list):
            raise ValueError("coverage references must be an array")
        return cls(
            schema_version=cast(int, data["schema_version"]),
            asserted_source_revision=cast(
                str, data["asserted_source_revision"]
            ),
            state=CoverageState(cast(str, data["state"])),
            authorized_root_aliases=_string_array(
                data["authorized_root_aliases"],
                field="authorized root aliases",
            ),
            exclusions=_string_array(
                data["exclusions"],
                field="coverage exclusions",
            ),
            failures=_string_array(
                data["failures"],
                field="coverage failures",
            ),
            ambiguity_evaluation=AmbiguityEvaluation(
                cast(str, data["ambiguity_evaluation"])
            ),
            references=tuple(
                ReferenceCoverage.from_dict(item) for item in data["references"]
            ),
            coverage_id=cast(str, data["coverage_id"]),
        )

    def to_json(self) -> str:
        return (
            json.dumps(
                asdict(self),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @staticmethod
    def identity_for(**fields: object) -> str:
        canonical = json.dumps(
            fields,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=lambda value: (
                value.value if isinstance(value, StrEnum) else asdict(value)
            ),
        ).encode("utf-8")
        return "pdf-coverage:sha256:" + hashlib.sha256(canonical).hexdigest()

    def by_citekey(self) -> dict[str, ReferenceCoverage]:
        return {item.citekey: item for item in self.references}


def _bounded_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
        raise ValueError(f"{field} must be a bounded non-empty string")
    return value


def _validate_sorted_strings(values: object, *, field: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) for item in values
    ):
        raise ValueError(f"{field} must be a string tuple")
    if any(not item or len(item) > _MAX_TEXT for item in values):
        raise ValueError(f"{field} contains an invalid string")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{field} must be sorted and unique")


def _string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError(f"{field} must be a string array")
    return tuple(value)


def _exact_object(
    value: object,
    *,
    fields: set[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    keys = set(value)
    missing = fields - keys
    unknown = keys - fields
    if missing or unknown:
        raise ValueError(
            f"{label} fields differ: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    return value
