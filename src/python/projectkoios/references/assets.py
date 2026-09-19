from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from projectkoios.references.identity import (
    ActorProvenance,
    IdentityProjection,
    ReferenceCandidate,
)
from projectkoios.references.io_limits import (
    ASSET_DISCOVERY_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_utf8_size,
    validate_json_text_nesting,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    PathLimitError,
    PathSafetyError,
    PlaceholderObservation,
    PlaceholderPreflightError,
    PlaceholderProbeSupport,
    PlaceholderStatus,
    RootPreflightEvidence,
    RootStorageClass,
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)


def _normalized_words(value: str) -> tuple[str, ...]:
    plain = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return tuple(re.findall(r"[a-z0-9]+", plain.lower()))


@dataclass(frozen=True)
class SearchRoot:
    alias: str
    path: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        validate_root_alias(self.alias, field="search-root alias")
        if not isinstance(self.path, Path):
            raise ValueError("search-root path must be a Path")
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("search-root storage class must be explicit")
        if (
            self.storage_class is RootStorageClass.LOCAL
            and self.placeholder_probe is not None
        ):
            raise ValueError("local search roots must not supply a cloud probe")


ASSET_AMBIGUITY_STATUSES = frozenset(
    {
        "no-heuristic-candidate-observed",
        "unresolved-single-heuristic-candidate",
        "unresolved-competing-bibliographic-candidates",
        "unresolved-alternate-source-versions",
        "unresolved-competing-candidates-and-source-versions",
    }
)


class AssetHeuristicKind(StrEnum):
    """Typed filename observations; no value is an identity decision."""

    EXACT_PROPOSED_CITEKEY_FILENAME = "exact-proposed-citekey-filename"
    PROPOSED_CITEKEY_IN_FILENAME = "proposed-citekey-in-filename"
    TITLE_TOKEN_OVERLAP = "title-token-overlap"
    YEAR_TOKEN_IN_FILENAME = "year-token-in-filename"


@dataclass(frozen=True)
class AssetHeuristicObservation:
    kind: AssetHeuristicKind
    matched_tokens: tuple[str, ...]
    compared_token_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AssetHeuristicKind):
            raise ValueError("asset heuristic kind is unsupported")
        if (
            not isinstance(self.matched_tokens, tuple)
            or len(self.matched_tokens) > 512
            or tuple(sorted(set(self.matched_tokens))) != self.matched_tokens
            or any(
                not item or bounded_utf8_size(item, max_bytes=4_096) > 4_096
                for item in self.matched_tokens
            )
        ):
            raise ValueError("asset heuristic tokens are invalid")
        if (
            type(self.compared_token_count) is not int
            or self.compared_token_count <= 0
            or self.compared_token_count > 4_096
            or self.compared_token_count < len(self.matched_tokens)
        ):
            raise ValueError("asset heuristic token count is invalid")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict) or set(value) != {
            "kind",
            "matched_tokens",
            "compared_token_count",
        }:
            raise ValueError("asset heuristic observation is malformed")
        tokens = value["matched_tokens"]
        if not isinstance(tokens, list) or any(
            not isinstance(item, str) for item in tokens
        ):
            raise ValueError("asset heuristic tokens are malformed")
        count = value["compared_token_count"]
        if type(count) is not int:
            raise ValueError("asset heuristic token count is malformed")
        try:
            kind = AssetHeuristicKind(value["kind"])
        except (TypeError, ValueError) as error:
            raise ValueError("asset heuristic kind is unsupported") from error
        return cls(kind, tuple(tokens), count)


@dataclass(frozen=True)
class AssetCandidate:
    candidate_id: str
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    root_alias: str
    relative_path: str
    match_status: str
    heuristic_observations: tuple[AssetHeuristicObservation, ...]
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        if (
            re.fullmatch(
                r"reference-candidate:sha256:[0-9a-f]{64}",
                self.candidate_id,
            )
            is None
        ):
            raise ValueError("asset candidate identity is invalid")
        validate_citekey(self.proposed_citekey, field="proposed citekey")
        if self.identity_status != "unaccepted-candidate":
            raise ValueError("asset candidate cannot claim accepted identity")
        if self.citekey_status != "proposed-noncanonical":
            raise ValueError("asset candidate citekey must be noncanonical")
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if self.match_status != "unresolved-heuristic-observation":
            raise ValueError("asset candidate match must remain unresolved")
        if (
            not isinstance(self.heuristic_observations, tuple)
            or not self.heuristic_observations
            or len(self.heuristic_observations) > 32
            or any(
                not isinstance(item, AssetHeuristicObservation)
                for item in self.heuristic_observations
            )
            or tuple(
                sorted(
                    self.heuristic_observations,
                    key=lambda item: (
                        item.kind.value,
                        item.matched_tokens,
                        item.compared_token_count,
                    ),
                )
            )
            != self.heuristic_observations
        ):
            raise ValueError("asset heuristic observations are invalid")
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("asset candidate SHA-256 must be lowercase hex")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("asset candidate byte size must be positive")

    @property
    def observation_id(self) -> str:
        return _stable_id("asset-heuristic-observation", asdict(self))


class AssetDispositionKind(StrEnum):
    AUTHORIZED_CANONICAL_CONTENT = "authorized-canonical-content"
    REJECTED_IDENTITY_MISMATCH = "rejected-identity-mismatch"
    RETAINED_ALTERNATE_VERSION = "retained-alternate-version"
    RETAINED_COMPETING_CANDIDATE = "retained-competing-candidate"


@dataclass(frozen=True)
class AssetCandidateDisposition:
    asset_observation_id: str
    disposition: AssetDispositionKind
    rationale: str

    def __post_init__(self) -> None:
        _validate_content_id(
            self.asset_observation_id,
            prefix="asset-heuristic-observation",
            field="asset observation identity",
        )
        if not isinstance(self.disposition, AssetDispositionKind):
            raise ValueError("asset disposition is unsupported")
        if (
            not isinstance(self.rationale, str)
            or not self.rationale.strip()
            or bounded_utf8_size(self.rationale, max_bytes=4_096) > 4_096
        ):
            raise ValueError("asset disposition rationale is invalid")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict) or set(value) != {
            "asset_observation_id",
            "disposition",
            "rationale",
        }:
            raise ValueError("asset disposition is malformed")
        try:
            disposition = AssetDispositionKind(value["disposition"])
        except (TypeError, ValueError) as error:
            raise ValueError("asset disposition is unsupported") from error
        if not isinstance(value["asset_observation_id"], str) or not isinstance(
            value["rationale"], str
        ):
            raise ValueError("asset disposition fields are malformed")
        return cls(
            asset_observation_id=value["asset_observation_id"],
            disposition=disposition,
            rationale=value["rationale"],
        )


@dataclass(frozen=True)
class CanonicalAssetAuthorization:
    """Exact human authorization for one byte identity and canonical name."""

    schema_version: int
    authority_kind: str
    actor: ActorProvenance
    asset_plan_id: str
    identity_projection_id: str
    reference_id: str
    canonical_citekey: str
    selected_asset_observation_id: str
    dispositions: tuple[AssetCandidateDisposition, ...]
    decision_id: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported canonical-asset decision schema")
        if self.authority_kind != "canonical-asset-authorization-decision":
            raise ValueError("unsupported canonical-asset decision kind")
        if not isinstance(self.actor, ActorProvenance):
            raise ValueError("canonical-asset actor provenance is invalid")
        for value, prefix, field_name in (
            (self.asset_plan_id, "asset-discovery-plan", "asset plan identity"),
            (
                self.identity_projection_id,
                "identity-projection",
                "identity projection identity",
            ),
            (self.reference_id, "canonical-reference", "reference identity"),
            (
                self.selected_asset_observation_id,
                "asset-heuristic-observation",
                "selected asset observation identity",
            ),
        ):
            _validate_content_id(value, prefix=prefix, field=field_name)
        validate_citekey(self.canonical_citekey, field="canonical citekey")
        if (
            not isinstance(self.dispositions, tuple)
            or not self.dispositions
            or len(self.dispositions)
            > _required_limit(
                ASSET_DISCOVERY_IO_LIMITS.max_candidates,
                "max_candidates",
            )
            or any(
                not isinstance(item, AssetCandidateDisposition)
                for item in self.dispositions
            )
        ):
            raise ValueError("canonical-asset dispositions are invalid")
        disposition_ids = tuple(
            item.asset_observation_id for item in self.dispositions
        )
        if disposition_ids != tuple(sorted(disposition_ids)) or len(
            disposition_ids
        ) != len(set(disposition_ids)):
            raise ValueError(
                "canonical-asset dispositions must be sorted and unique"
            )
        selected = tuple(
            item
            for item in self.dispositions
            if item.disposition
            is AssetDispositionKind.AUTHORIZED_CANONICAL_CONTENT
        )
        if (
            len(selected) != 1
            or selected[0].asset_observation_id
            != self.selected_asset_observation_id
        ):
            raise ValueError(
                "canonical-asset decision must authorize exactly one asset"
            )
        expected = _stable_id(
            "canonical-asset-decision", self._identity_payload()
        )
        if self.decision_id != expected:
            raise ValueError("canonical-asset decision identity does not match")

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority_kind": self.authority_kind,
            "actor": self.actor,
            "asset_plan_id": self.asset_plan_id,
            "identity_projection_id": self.identity_projection_id,
            "reference_id": self.reference_id,
            "canonical_citekey": self.canonical_citekey,
            "selected_asset_observation_id": (
                self.selected_asset_observation_id
            ),
            "dispositions": self.dispositions,
        }

    @classmethod
    def create(
        cls,
        *,
        plan: AssetDiscoveryPlan,
        identity_projection: IdentityProjection,
        reference_id: str,
        selected_asset_observation_id: str,
        actor: ActorProvenance,
        dispositions: tuple[AssetCandidateDisposition, ...],
    ) -> Self:
        reference, canonical_citekey = _active_reference_and_name(
            identity_projection, reference_id
        )
        relevant_ids = plan.relevant_observation_ids(reference.candidate_ids)
        supplied_ids = {item.asset_observation_id for item in dispositions}
        if supplied_ids != set(relevant_ids):
            raise ValueError(
                "asset decision must disposition every competing candidate "
                "and alternate version"
            )
        selected = plan.candidate_by_observation_id(
            selected_asset_observation_id
        )
        if selected.candidate_id not in reference.candidate_ids:
            raise ValueError(
                "selected asset is not linked to the accepted reference"
            )
        ordered_dispositions = tuple(
            sorted(
                dispositions,
                key=lambda item: item.asset_observation_id,
            )
        )
        payload = {
            "schema_version": 1,
            "authority_kind": "canonical-asset-authorization-decision",
            "actor": actor,
            "asset_plan_id": plan.plan_id,
            "identity_projection_id": identity_projection.projection_id,
            "reference_id": reference_id,
            "canonical_citekey": canonical_citekey,
            "selected_asset_observation_id": selected_asset_observation_id,
            "dispositions": ordered_dispositions,
        }
        return cls(
            schema_version=1,
            authority_kind="canonical-asset-authorization-decision",
            actor=actor,
            asset_plan_id=plan.plan_id,
            identity_projection_id=identity_projection.projection_id,
            reference_id=reference_id,
            canonical_citekey=canonical_citekey,
            selected_asset_observation_id=selected_asset_observation_id,
            dispositions=ordered_dispositions,
            decision_id=_stable_id("canonical-asset-decision", payload),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Self:
        validate_json_text_nesting(
            text,
            limits=ASSET_DISCOVERY_IO_LIMITS,
            resource="canonical asset decision JSON",
        )
        data = json.loads(text)
        expected = {
            "schema_version",
            "authority_kind",
            "actor",
            "asset_plan_id",
            "identity_projection_id",
            "reference_id",
            "canonical_citekey",
            "selected_asset_observation_id",
            "dispositions",
            "decision_id",
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError("canonical-asset decision fields are invalid")
        disposition_data = data["dispositions"]
        if not isinstance(disposition_data, list):
            raise ValueError("canonical-asset dispositions must be an array")
        value = cls(
            schema_version=data["schema_version"],
            authority_kind=data["authority_kind"],
            actor=ActorProvenance.from_dict(data["actor"]),
            asset_plan_id=data["asset_plan_id"],
            identity_projection_id=data["identity_projection_id"],
            reference_id=data["reference_id"],
            canonical_citekey=data["canonical_citekey"],
            selected_asset_observation_id=data["selected_asset_observation_id"],
            dispositions=tuple(
                AssetCandidateDisposition.from_dict(item)
                for item in disposition_data
            ),
            decision_id=data["decision_id"],
        )
        if text != value.to_json():
            raise ValueError("canonical asset decision JSON is noncanonical")
        return value


@dataclass(frozen=True)
class AssetDiscoveryPlan:
    schema_version: int
    coverage_status: str
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    root_preflights: tuple[RootPreflightEvidence, ...]
    file_observations: tuple[PlaceholderObservation, ...]
    candidates: tuple[AssetCandidate, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 4:
            raise ValueError(
                "unsupported asset-plan schema version; legacy plans do not "
                "carry non-authoritative typed heuristics"
            )
        if self.coverage_status != "complete":
            raise ValueError(
                "published asset plans must have complete coverage"
            )
        if self.effective_limits.profile != ASSET_DISCOVERY_IO_LIMITS.profile:
            raise ValueError("asset-plan I/O-limit profile is incompatible")
        if self.effective_limits_id != self.effective_limits.evidence_id:
            raise ValueError("asset-plan I/O-limit identity conflicts")
        if not isinstance(self.root_preflights, tuple) or any(
            not isinstance(item, RootPreflightEvidence)
            for item in self.root_preflights
        ):
            raise ValueError("asset-plan root preflights are invalid")
        aliases = tuple(item.root_alias for item in self.root_preflights)
        if aliases != tuple(sorted(aliases)) or len(aliases) != len(
            set(aliases)
        ):
            raise ValueError(
                "asset-plan root preflights must be alias-sorted and unique"
            )
        root_evidence = {item.root_alias: item for item in self.root_preflights}
        if not isinstance(self.file_observations, tuple):
            raise ValueError("asset-plan file observations must be a tuple")
        if self.file_observations:
            raise ValueError(
                "complete asset plans cannot contain skipped file observations"
            )
        observation_keys = tuple(
            (item.root_alias, item.relative_path or "")
            for item in self.file_observations
        )
        if observation_keys != tuple(sorted(observation_keys)):
            raise ValueError("asset-plan file observations must be sorted")
        for observation in self.file_observations:
            root = root_evidence.get(observation.root_alias)
            if (
                root is None
                or observation.storage_class is not root.storage_class
                or observation.probe_id != root.probe_id
                or observation.status
                in {
                    PlaceholderStatus.ORDINARY_FILE,
                    PlaceholderStatus.UNSUPPORTED_PLATFORM,
                    PlaceholderStatus.AMBIGUOUS,
                }
            ):
                raise ValueError("asset-plan file observation conflicts")
        if (
            not isinstance(self.candidates, tuple)
            or len(self.candidates)
            > _required_limit(
                self.effective_limits.max_candidates,
                "max_candidates",
            )
            or any(
                not isinstance(candidate, AssetCandidate)
                for candidate in self.candidates
            )
        ):
            raise ValueError("asset-plan candidates are invalid or unbounded")
        if any(
            candidate.root_alias not in root_evidence
            for candidate in self.candidates
        ):
            raise ValueError("asset candidate root has no preflight evidence")
        candidate_keys = tuple(
            (
                item.proposed_citekey,
                item.candidate_id,
                item.root_alias,
                item.relative_path,
                item.sha256,
                item.observation_id,
            )
            for item in self.candidates
        )
        if candidate_keys != tuple(sorted(candidate_keys)) or len(
            {item.observation_id for item in self.candidates}
        ) != len(self.candidates):
            raise ValueError("asset candidates must be sorted and unique")

    @property
    def plan_id(self) -> str:
        return (
            "asset-discovery-plan:sha256:"
            + hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
        )

    def candidate_by_observation_id(
        self, observation_id: str
    ) -> AssetCandidate:
        matches = tuple(
            item
            for item in self.candidates
            if item.observation_id == observation_id
        )
        if len(matches) != 1:
            raise ValueError("asset observation is not unique in the plan")
        return matches[0]

    def connected_candidates(
        self, candidate_ids: tuple[str, ...]
    ) -> tuple[AssetCandidate, ...]:
        """Return the complete candidate/file connected component."""
        linked_candidate_ids = set(candidate_ids)
        linked_files: set[tuple[str, str, str]] = set()
        changed = True
        while changed:
            prior_candidates = len(linked_candidate_ids)
            prior_files = len(linked_files)
            linked_files.update(
                (item.root_alias, item.relative_path, item.sha256)
                for item in self.candidates
                if item.candidate_id in linked_candidate_ids
            )
            linked_candidate_ids.update(
                item.candidate_id
                for item in self.candidates
                if (item.root_alias, item.relative_path, item.sha256)
                in linked_files
            )
            changed = (
                len(linked_candidate_ids) != prior_candidates
                or len(linked_files) != prior_files
            )
        return tuple(
            item
            for item in self.candidates
            if item.candidate_id in linked_candidate_ids
            and (item.root_alias, item.relative_path, item.sha256)
            in linked_files
        )

    def relevant_observation_ids(
        self, accepted_candidate_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Retain accepted candidates and every connected ambiguity."""
        return tuple(
            sorted(
                item.observation_id
                for item in self.connected_candidates(accepted_candidate_ids)
            )
        )

    def ambiguity_status(self, candidate_id: str) -> str:
        direct = tuple(
            item
            for item in self.candidates
            if item.candidate_id == candidate_id
        )
        if not direct:
            return "no-heuristic-candidate-observed"
        connected = self.connected_candidates((candidate_id,))
        competing = any(item.candidate_id != candidate_id for item in connected)
        alternate_versions = len({item.sha256 for item in connected}) > 1
        if competing and alternate_versions:
            return "unresolved-competing-candidates-and-source-versions"
        if competing:
            return "unresolved-competing-bibliographic-candidates"
        if alternate_versions:
            return "unresolved-alternate-source-versions"
        return "unresolved-single-heuristic-candidate"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        limits: ReferenceIOLimits = ASSET_DISCOVERY_IO_LIMITS,
    ) -> AssetDiscoveryPlan:
        validate_json_text_nesting(
            text,
            limits=limits,
            resource="asset discovery plan JSON",
        )
        data = json.loads(text)
        _validate_json_depth(data, limits=limits)
        if not isinstance(data, dict):
            raise ValueError("asset plan must be an object")
        expected_fields = {
            "schema_version",
            "coverage_status",
            "effective_limits",
            "effective_limits_id",
            "root_preflights",
            "file_observations",
            "candidates",
        }
        if set(data) != expected_fields:
            raise ValueError("asset-plan fields are incomplete or unknown")
        if data.get("schema_version") != 4:
            raise ValueError(
                "unsupported asset-plan schema version; legacy plans do not "
                "carry non-authoritative typed heuristics"
            )
        candidates_data = data.get("candidates")
        if not isinstance(candidates_data, list):
            raise ValueError("asset-plan candidates must be an array")
        max_candidates = _required_limit(
            limits.max_candidates,
            "max_candidates",
        )
        if len(candidates_data) > max_candidates:
            raise ReferenceIOLimitError(
                resource="asset discovery plan candidates",
                limit_name="max_candidates",
                limit=max_candidates,
                observed=len(candidates_data),
                limits=limits,
            )
        limits_data = data.get("effective_limits")
        if not isinstance(limits_data, dict):
            raise ValueError("asset-plan effective limits are missing")
        try:
            recorded_limits = ReferenceIOLimits(**limits_data)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "asset-plan effective limits are malformed"
            ) from error
        candidate_fields = {
            "candidate_id",
            "proposed_citekey",
            "identity_status",
            "citekey_status",
            "root_alias",
            "relative_path",
            "match_status",
            "heuristic_observations",
            "sha256",
            "byte_size",
        }
        string_fields = candidate_fields - {
            "heuristic_observations",
            "byte_size",
        }
        if any(
            not isinstance(item, dict)
            or set(item) != candidate_fields
            or any(not isinstance(item[field], str) for field in string_fields)
            or type(item["byte_size"]) is not int
            or not isinstance(item["heuristic_observations"], list)
            for item in candidates_data
        ):
            raise ValueError(
                "asset-plan candidate fields differ or are invalid"
            )
        root_preflights = _parse_root_preflights(data["root_preflights"])
        file_observations = _parse_file_observations(data["file_observations"])
        plan = cls(
            schema_version=4,
            coverage_status=data["coverage_status"],
            effective_limits=recorded_limits,
            effective_limits_id=data["effective_limits_id"],
            root_preflights=root_preflights,
            file_observations=file_observations,
            candidates=tuple(
                AssetCandidate(
                    candidate_id=item["candidate_id"],
                    proposed_citekey=item["proposed_citekey"],
                    identity_status=item["identity_status"],
                    citekey_status=item["citekey_status"],
                    root_alias=item["root_alias"],
                    relative_path=item["relative_path"],
                    match_status=item["match_status"],
                    heuristic_observations=tuple(
                        AssetHeuristicObservation.from_dict(observation)
                        for observation in item["heuristic_observations"]
                    ),
                    sha256=item["sha256"],
                    byte_size=int(item["byte_size"]),
                )
                for item in candidates_data
            ),
        )
        if text != plan.to_json():
            raise ValueError("asset discovery plan JSON is noncanonical")
        return plan


class AssetDiscoveryPlanner:
    """Produce conservative PDF candidates without mutating any source."""

    def scan(
        self,
        records: tuple[ReferenceCandidate, ...],
        roots: tuple[SearchRoot, ...],
        *,
        limits: ReferenceIOLimits = ASSET_DISCOVERY_IO_LIMITS,
    ) -> AssetDiscoveryPlan:
        max_files = _required_limit(limits.max_files, "max_files")
        max_entries = _required_limit(limits.max_entries, "max_entries")
        max_file_bytes = _required_limit(
            limits.max_file_bytes,
            "max_file_bytes",
        )
        max_total_bytes = _required_limit(
            limits.max_total_bytes,
            "max_total_bytes",
        )
        max_candidates = _required_limit(
            limits.max_candidates,
            "max_candidates",
        )
        max_match_evaluations = _required_limit(
            limits.max_match_evaluations,
            "max_match_evaluations",
        )
        if len(records) > max_entries:
            raise ReferenceIOLimitError(
                resource="reference candidates",
                limit_name="max_entries",
                limit=max_entries,
                observed=len(records),
                limits=limits,
            )
        if len(roots) > min(max_files, max_entries):
            raise ReferenceIOLimitError(
                resource="asset search roots",
                limit_name="max_entries",
                limit=min(max_files, max_entries),
                observed=len(roots),
                limits=limits,
            )
        candidates: list[AssetCandidate] = []
        file_observations: list[PlaceholderObservation] = []
        authorized = _authorized_roots(roots)
        match_index = _MatchIndex(records)
        files_seen = 0
        observed_bytes = 0
        match_evaluations = 0
        entries_per_root = max_entries // len(roots)
        for root in roots:
            safe_root = authorized[root.alias]
            remaining_files = max_files - files_seen
            if remaining_files <= 0:
                raise ReferenceIOLimitError(
                    resource="asset search",
                    limit_name="max_files",
                    limit=max_files,
                    observed=files_seen + 1,
                    limits=limits,
                )
            try:
                relative_files = safe_root.iter_files(
                    suffix=".pdf",
                    recursive=True,
                    max_files=remaining_files,
                    max_entries=entries_per_root,
                    max_depth=64,
                )
            except PathLimitError as error:
                raise _limit_error(error, limits) from error
            files_seen += len(relative_files)
            for relative in relative_files:
                preflight = safe_root.preflight_file(relative)
                if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
                    raise PlaceholderPreflightError(preflight)
                path = safe_root.child_path(relative)
                matches: list[
                    tuple[
                        ReferenceCandidate,
                        tuple[AssetHeuristicObservation, ...],
                    ]
                ] = []
                for record in match_index.potential_matches(path.stem):
                    match_evaluations += 1
                    if match_evaluations > max_match_evaluations:
                        raise ReferenceIOLimitError(
                            resource="asset match evaluations",
                            limit_name="max_match_evaluations",
                            limit=max_match_evaluations,
                            observed=match_evaluations,
                            limits=limits,
                        )
                    observations = self._observe_heuristics(record, path)
                    if observations:
                        matches.append((record, observations))
                if not matches:
                    continue
                try:
                    observation = safe_root.observe_file(
                        relative,
                        max_bytes=max_file_bytes,
                        prefix_bytes=4,
                    )
                except PathLimitError as error:
                    raise _limit_error(error, limits) from error
                if observation.byte_size <= 0:
                    raise ValueError("asset candidate is empty")
                if observation.prefix != b"%PDF":
                    raise ValueError(
                        f"asset candidate is not a PDF: {relative.as_posix()}"
                    )
                observed_bytes += observation.byte_size
                if observed_bytes > max_total_bytes:
                    raise ReferenceIOLimitError(
                        resource="asset discovery",
                        limit_name="max_total_bytes",
                        limit=max_total_bytes,
                        observed=observed_bytes,
                        limits=limits,
                    )
                for record, heuristic_observations in matches:
                    candidates.append(
                        AssetCandidate(
                            candidate_id=record.candidate_id,
                            proposed_citekey=record.proposed_citekey,
                            identity_status=record.lifecycle_status,
                            citekey_status=record.citekey_status,
                            root_alias=root.alias,
                            relative_path=relative.as_posix(),
                            match_status="unresolved-heuristic-observation",
                            heuristic_observations=heuristic_observations,
                            sha256=observation.sha256,
                            byte_size=observation.byte_size,
                        )
                    )
                    if len(candidates) > max_candidates:
                        raise ReferenceIOLimitError(
                            resource="asset candidates",
                            limit_name="max_candidates",
                            limit=max_candidates,
                            observed=len(candidates),
                            limits=limits,
                        )
        ordered = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.proposed_citekey,
                    item.candidate_id,
                    item.root_alias,
                    item.relative_path,
                    item.sha256,
                    item.observation_id,
                ),
            )
        )
        return AssetDiscoveryPlan(
            schema_version=4,
            coverage_status="complete",
            effective_limits=limits,
            effective_limits_id=limits.evidence_id,
            root_preflights=tuple(
                sorted(
                    (
                        authorized[root.alias].preflight_evidence
                        for root in roots
                    ),
                    key=lambda item: item.root_alias,
                )
            ),
            file_observations=tuple(
                sorted(
                    file_observations,
                    key=lambda item: (
                        item.root_alias,
                        item.relative_path or "",
                    ),
                )
            ),
            candidates=ordered,
        )

    @staticmethod
    def _observe_heuristics(
        record: ReferenceCandidate,
        path: Path,
    ) -> tuple[AssetHeuristicObservation, ...]:
        stem_words = _normalized_words(path.stem)
        stem_joined = "".join(stem_words)
        key_tokens = _normalized_words(record.proposed_citekey)
        key_joined = "".join(key_tokens)
        observations: list[AssetHeuristicObservation] = []
        has_primary_match = False
        if stem_joined == key_joined:
            has_primary_match = True
            observations.append(
                AssetHeuristicObservation(
                    AssetHeuristicKind.EXACT_PROPOSED_CITEKEY_FILENAME,
                    tuple(sorted(set(key_tokens))),
                    max(1, len(set(key_tokens))),
                )
            )
        elif key_joined and key_joined in stem_joined:
            has_primary_match = True
            observations.append(
                AssetHeuristicObservation(
                    AssetHeuristicKind.PROPOSED_CITEKEY_IN_FILENAME,
                    tuple(sorted(set(key_tokens))),
                    max(1, len(set(key_tokens))),
                )
            )

        significant = {
            word
            for word in _normalized_words(record.title or "")
            if len(word) >= 4
        }
        matching_title = tuple(sorted(significant & set(stem_words)))
        if significant and len(matching_title) / len(significant) >= 0.5:
            has_primary_match = True
            observations.append(
                AssetHeuristicObservation(
                    AssetHeuristicKind.TITLE_TOKEN_OVERLAP,
                    matching_title,
                    len(significant),
                )
            )
        if record.year and record.year in stem_words:
            observations.append(
                AssetHeuristicObservation(
                    AssetHeuristicKind.YEAR_TOKEN_IN_FILENAME,
                    (record.year,),
                    1,
                )
            )
        if not has_primary_match:
            return ()
        return tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.kind.value,
                    item.matched_tokens,
                    item.compared_token_count,
                ),
            )
        )


@dataclass(frozen=True)
class AssetMaterializationResult:
    path: Path
    created: bool

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or type(self.created) is not bool:
            raise ValueError("asset materialization result is invalid")


def materialize_asset_with_result(
    candidate: AssetCandidate,
    *,
    authorization: CanonicalAssetAuthorization,
    plan: AssetDiscoveryPlan,
    identity_projection: IdentityProjection,
    expected_root_preflight: RootPreflightEvidence,
    roots: tuple[SearchRoot, ...],
    destination_directory: Path,
    destination_storage_class: RootStorageClass,
    limits: ReferenceIOLimits = ASSET_DISCOVERY_IO_LIMITS,
) -> AssetMaterializationResult:
    """Materialize exact authorized bytes and report whether it was created."""
    _validate_authorization(
        candidate=candidate,
        authorization=authorization,
        plan=plan,
        identity_projection=identity_projection,
    )
    root_paths = _authorized_roots(roots)
    if candidate.root_alias not in root_paths:
        raise ValueError("candidate search-root alias was not supplied")
    if (
        expected_root_preflight.root_alias != candidate.root_alias
        or root_paths[candidate.root_alias].preflight_evidence
        != expected_root_preflight
    ):
        raise ValueError("candidate root preflight evidence changed")
    relative = validate_relative_path(candidate.relative_path)
    root_paths[candidate.root_alias].require_readable_file(relative)
    max_file_bytes = _required_limit(
        limits.max_file_bytes,
        "max_file_bytes",
    )
    if candidate.byte_size > max_file_bytes:
        raise ReferenceIOLimitError(
            resource="asset candidate",
            limit_name="max_file_bytes",
            limit=max_file_bytes,
            observed=candidate.byte_size,
            limits=limits,
        )

    try:
        source_observation = root_paths[candidate.root_alias].observe_file(
            relative,
            max_bytes=max_file_bytes,
            prefix_bytes=4,
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    if source_observation.prefix != b"%PDF":
        raise ValueError("candidate source is no longer a PDF")
    if (
        source_observation.sha256 != candidate.sha256
        or source_observation.byte_size != candidate.byte_size
    ):
        raise ValueError("candidate source hash or size changed after planning")

    destination_root = AuthorizedRoot.create(
        destination_directory,
        label="asset destination root",
        root_alias="asset-destination",
        storage_class=destination_storage_class,
    )
    filename = f"{authorization.canonical_citekey}.pdf"
    state = destination_root.state(filename)
    destination = destination_root.child_path(filename)
    if state == "regular":
        destination_observation = destination_root.observe_file(
            filename,
            max_bytes=max_file_bytes,
            prefix_bytes=4,
        )
        if (
            destination_observation.prefix == b"%PDF"
            and destination_observation.sha256 == candidate.sha256
            and destination_observation.byte_size == candidate.byte_size
        ):
            return AssetMaterializationResult(destination, created=False)
        raise FileExistsError(
            f"destination exists with different bytes: {destination}"
        )
    if state != "missing":
        raise FileExistsError(f"destination is not a file: {destination}")
    try:
        created = destination_root.copy_file_from(
            root_paths[candidate.root_alias],
            relative,
            filename,
            max_bytes=max_file_bytes,
            expected_sha256=candidate.sha256,
            expected_size=candidate.byte_size,
        )
        return AssetMaterializationResult(created, created=True)
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    except PathSafetyError as error:
        if "source identity changed" in str(error):
            raise ValueError(
                "candidate source hash or size changed after planning"
            ) from error
        raise


def materialize_asset(
    candidate: AssetCandidate,
    *,
    authorization: CanonicalAssetAuthorization,
    plan: AssetDiscoveryPlan,
    identity_projection: IdentityProjection,
    expected_root_preflight: RootPreflightEvidence,
    roots: tuple[SearchRoot, ...],
    destination_directory: Path,
    destination_storage_class: RootStorageClass,
    limits: ReferenceIOLimits = ASSET_DISCOVERY_IO_LIMITS,
) -> Path:
    """Materialize exact authorized bytes under a replayed canonical name."""
    return materialize_asset_with_result(
        candidate,
        authorization=authorization,
        plan=plan,
        identity_projection=identity_projection,
        expected_root_preflight=expected_root_preflight,
        roots=roots,
        destination_directory=destination_directory,
        destination_storage_class=destination_storage_class,
        limits=limits,
    ).path


def rollback_materialized_asset(
    result: AssetMaterializationResult,
    *,
    candidate: AssetCandidate,
    authorization: CanonicalAssetAuthorization,
    destination_directory: Path,
    destination_storage_class: RootStorageClass,
    limits: ReferenceIOLimits = ASSET_DISCOVERY_IO_LIMITS,
) -> None:
    """Remove only exact bytes newly created by this materialization."""
    if not isinstance(result, AssetMaterializationResult) or not result.created:
        raise ValueError("rollback requires a newly materialized asset")
    max_file_bytes = _required_limit(
        limits.max_file_bytes,
        "max_file_bytes",
    )
    destination_root = AuthorizedRoot.create(
        destination_directory,
        label="asset destination root",
        root_alias="asset-destination",
        storage_class=destination_storage_class,
    )
    filename = f"{authorization.canonical_citekey}.pdf"
    if result.path != destination_root.child_path(filename):
        raise ValueError("rollback result names a different destination")
    destination_root.remove_file_if_exact(
        filename,
        expected_sha256=candidate.sha256,
        expected_size=candidate.byte_size,
        max_bytes=max_file_bytes,
    )


class _MatchIndex:
    """Bound filename matching independently of bibliography cardinality."""

    _END = ""

    def __init__(self, records: tuple[ReferenceCandidate, ...]) -> None:
        self._records = {record.candidate_id: record for record in records}
        self._title_words: dict[str, set[str]] = {}
        self._citekey_trie: dict[str, Any] = {}
        for record in records:
            key = "".join(_normalized_words(record.proposed_citekey))
            node = self._citekey_trie
            for character in key:
                node = node.setdefault(character, {})
            node.setdefault(self._END, set()).add(record.candidate_id)
            for word in _normalized_words(record.title or ""):
                if len(word) >= 4:
                    self._title_words.setdefault(word, set()).add(
                        record.candidate_id
                    )

    def potential_matches(self, stem: str) -> tuple[ReferenceCandidate, ...]:
        words = _normalized_words(stem)
        joined = "".join(words)
        candidate_ids: set[str] = set()
        for word in words:
            candidate_ids.update(self._title_words.get(word, ()))
        for start in range(len(joined)):
            node = self._citekey_trie
            for character in joined[start:]:
                child = node.get(character)
                if not isinstance(child, dict):
                    break
                node = child
                terminal = node.get(self._END)
                if isinstance(terminal, set):
                    candidate_ids.update(terminal)
        return tuple(
            self._records[candidate_id]
            for candidate_id in sorted(candidate_ids)
        )


def _validate_authorization(
    *,
    candidate: AssetCandidate,
    authorization: CanonicalAssetAuthorization,
    plan: AssetDiscoveryPlan,
    identity_projection: IdentityProjection,
) -> None:
    if candidate not in plan.candidates:
        raise ValueError("asset candidate is not in the supplied plan")
    if authorization.asset_plan_id != plan.plan_id:
        raise ValueError("canonical-asset decision names a different plan")
    if (
        authorization.identity_projection_id
        != identity_projection.projection_id
    ):
        raise ValueError(
            "canonical-asset decision names a different identity projection"
        )
    reference, canonical_citekey = _active_reference_and_name(
        identity_projection, authorization.reference_id
    )
    if authorization.canonical_citekey != canonical_citekey:
        raise ValueError("canonical-asset decision names a stale citekey")
    if candidate.candidate_id not in reference.candidate_ids:
        raise ValueError("asset candidate is outside the accepted reference")
    if candidate.observation_id != authorization.selected_asset_observation_id:
        raise ValueError("asset candidate was not selected by the decision")
    relevant = plan.relevant_observation_ids(reference.candidate_ids)
    disposition_ids = tuple(
        item.asset_observation_id for item in authorization.dispositions
    )
    if disposition_ids != relevant:
        raise ValueError(
            "canonical-asset decision omits competing candidates or versions"
        )


def _active_reference_and_name(
    projection: IdentityProjection,
    reference_id: str,
) -> tuple[Any, str]:
    if not isinstance(projection, IdentityProjection):
        raise TypeError("identity_projection must be replay validated")
    references = tuple(
        item
        for item in projection.accepted_references
        if item.reference_id == reference_id
        and item.reference_id in projection.active_reference_ids
    )
    names = tuple(
        item
        for item in projection.name_history
        if item.reference_id == reference_id and item.active
    )
    if len(references) != 1 or len(names) != 1:
        raise ValueError("canonical asset requires one active reference name")
    return references[0], names[0].canonical_citekey


def _stable_id(kind: str, value: object) -> str:
    payload = json.dumps(
        asdict(value) if is_dataclass(value) else value,  # type: ignore[arg-type]
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(payload).hexdigest()}"


def _json_default(value: object) -> object:
    if is_dataclass(value):
        return asdict(value)  # type: ignore[arg-type]
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _validate_content_id(value: str, *, prefix: str, field: str) -> None:
    if (
        re.fullmatch(rf"{re.escape(prefix)}:sha256:[0-9a-f]{{64}}", value)
        is None
    ):
        raise ValueError(f"{field} is invalid")


def _parse_root_preflights(value: object) -> tuple[RootPreflightEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("asset-plan root preflights must be an array")
    expected = {
        "root_alias",
        "storage_class",
        "probe_id",
        "probe_support",
    }
    parsed: list[RootPreflightEvidence] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("asset-plan root preflight is malformed")
        try:
            storage_class = RootStorageClass(item["storage_class"])
            raw_support = item["probe_support"]
            support = (
                None
                if raw_support is None
                else PlaceholderProbeSupport(raw_support)
            )
            parsed.append(
                RootPreflightEvidence(
                    root_alias=item["root_alias"],
                    storage_class=storage_class,
                    probe_id=item["probe_id"],
                    probe_support=support,
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "asset-plan root preflight is malformed"
            ) from error
    return tuple(parsed)


def _parse_file_observations(
    value: object,
) -> tuple[PlaceholderObservation, ...]:
    if not isinstance(value, list):
        raise ValueError("asset-plan file observations must be an array")
    expected = {
        "root_alias",
        "relative_path",
        "storage_class",
        "probe_id",
        "status",
    }
    parsed: list[PlaceholderObservation] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("asset-plan file observation is malformed")
        try:
            parsed.append(
                PlaceholderObservation(
                    root_alias=item["root_alias"],
                    relative_path=item["relative_path"],
                    storage_class=RootStorageClass(item["storage_class"]),
                    probe_id=item["probe_id"],
                    status=PlaceholderStatus(item["status"]),
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "asset-plan file observation is malformed"
            ) from error
    return tuple(parsed)


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"asset-discovery I/O profile must define {name}")
    return value


def _limit_error(
    error: PathLimitError,
    limits: ReferenceIOLimits,
) -> ReferenceIOLimitError:
    return ReferenceIOLimitError(
        resource=error.resource,
        limit_name=error.limit_name,
        limit=error.limit,
        observed=error.observed,
        limits=limits,
    )


def _validate_json_depth(
    value: object,
    *,
    limits: ReferenceIOLimits,
) -> None:
    max_depth = _required_limit(limits.max_json_depth, "max_json_depth")
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            raise ReferenceIOLimitError(
                resource="asset discovery plan JSON",
                limit_name="max_json_depth",
                limit=max_depth,
                observed=depth,
                limits=limits,
            )
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            maximum_text = _required_limit(
                limits.max_text_bytes,
                "max_text_bytes",
            )
            observed = bounded_utf8_size(item, max_bytes=maximum_text)
            if observed > maximum_text:
                raise ReferenceIOLimitError(
                    resource="asset discovery plan JSON text",
                    limit_name="max_text_bytes",
                    limit=maximum_text,
                    observed=observed,
                    limits=limits,
                )


def _authorized_roots(
    roots: tuple[SearchRoot, ...],
) -> dict[str, AuthorizedRoot]:
    if not roots:
        raise ValueError("at least one search root is required")
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("search-root aliases must be unique")
    return {
        root.alias: AuthorizedRoot.existing(
            root.path,
            label=f"search root {root.alias!r}",
            root_alias=root.alias,
            storage_class=root.storage_class,
            placeholder_probe=root.placeholder_probe,
        )
        for root in roots
    }
