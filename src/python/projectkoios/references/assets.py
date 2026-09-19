from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from projectkoios.references.identity import ReferenceCandidate
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


@dataclass(frozen=True)
class AssetCandidate:
    candidate_id: str
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    root_alias: str
    relative_path: str
    score: float
    evidence: tuple[str, ...]
    recommendation: str
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
        validate_citekey(
            self.proposed_citekey,
            field="proposed citekey",
        )
        if self.identity_status != "unaccepted-candidate":
            raise ValueError("asset candidate cannot claim accepted identity")
        if self.citekey_status != "proposed-noncanonical":
            raise ValueError("asset candidate citekey must be noncanonical")
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if not isinstance(self.score, float) or not 0.0 <= self.score <= 1.0:
            raise ValueError("asset candidate score must be finite in [0, 1]")
        if (
            not isinstance(self.evidence, tuple)
            or len(self.evidence) > 32
            or any(
                not isinstance(item, str)
                or not item
                or bounded_utf8_size(item, max_bytes=4_096) > 4_096
                for item in self.evidence
            )
        ):
            raise ValueError("asset candidate evidence is invalid or unbounded")
        if self.recommendation not in {"strong-candidate", "manual-review"}:
            raise ValueError("asset candidate recommendation is unsupported")
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("asset candidate SHA-256 must be lowercase hex")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("asset candidate byte size must be positive")

    @property
    def materialized_filename(self) -> str:
        digest = self.candidate_id.rsplit(":", maxsplit=1)[-1]
        return f"{self.proposed_citekey}.candidate-{digest[:16]}.pdf"


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
        if self.schema_version != 3:
            raise ValueError("unsupported asset-plan schema version")
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
        if any(
            candidate.root_alias not in root_evidence
            for candidate in self.candidates
        ):
            raise ValueError("asset candidate root has no preflight evidence")

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
        if data.get("schema_version") != 3:
            raise ValueError("unsupported asset-plan schema version")
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
            "score",
            "evidence",
            "recommendation",
            "sha256",
            "byte_size",
        }
        string_fields = candidate_fields - {
            "score",
            "evidence",
            "byte_size",
        }
        if any(
            not isinstance(item, dict)
            or set(item) != candidate_fields
            or any(not isinstance(item[field], str) for field in string_fields)
            or type(item["score"]) not in {int, float}
            or type(item["byte_size"]) is not int
            or not isinstance(item["evidence"], list)
            or any(not isinstance(value, str) for value in item["evidence"])
            for item in candidates_data
        ):
            raise ValueError(
                "asset-plan candidate fields differ or are invalid"
            )
        root_preflights = _parse_root_preflights(data["root_preflights"])
        file_observations = _parse_file_observations(data["file_observations"])
        plan = cls(
            schema_version=3,
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
                    score=float(item["score"]),
                    evidence=tuple(item["evidence"]),
                    recommendation=item["recommendation"],
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
                    tuple[ReferenceCandidate, float, tuple[str, ...]]
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
                    score, evidence = self._score(record, path)
                    if score >= 0.5:
                        matches.append((record, score, evidence))
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
                for record, score, evidence in matches:
                    candidates.append(
                        AssetCandidate(
                            candidate_id=record.candidate_id,
                            proposed_citekey=record.proposed_citekey,
                            identity_status=record.lifecycle_status,
                            citekey_status=record.citekey_status,
                            root_alias=root.alias,
                            relative_path=relative.as_posix(),
                            score=score,
                            evidence=evidence,
                            recommendation=(
                                "strong-candidate"
                                if score >= 0.9
                                else "manual-review"
                            ),
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
                    -item.score,
                    item.root_alias,
                    item.relative_path,
                ),
            )
        )
        return AssetDiscoveryPlan(
            schema_version=3,
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
    def _score(
        record: ReferenceCandidate,
        path: Path,
    ) -> tuple[float, tuple[str, ...]]:
        stem_words = _normalized_words(path.stem)
        stem_joined = "".join(stem_words)
        key_joined = "".join(_normalized_words(record.proposed_citekey))
        evidence: list[str] = []
        score = 0.0
        if stem_joined == key_joined:
            score = 1.0
            evidence.append("exact-citekey-filename")
        elif key_joined and key_joined in stem_joined:
            score = 0.9
            evidence.append("citekey-contained-in-filename")

        title_words = _normalized_words(record.title or "")
        significant = tuple(word for word in title_words if len(word) >= 4)
        if significant:
            overlap = len(set(significant) & set(stem_words)) / len(
                set(significant)
            )
            if overlap >= 0.8 and score < 0.95:
                score = 0.95
                evidence.append("strong-title-filename-match")
            elif overlap >= 0.5 and score < 0.6:
                score = 0.6
                evidence.append("partial-title-filename-match")

        if record.year and record.year in stem_words:
            evidence.append("year-in-filename")
            score = min(1.0, score + 0.05)
        return score, tuple(evidence)


def materialize_asset(
    candidate: AssetCandidate,
    *,
    expected_root_preflight: RootPreflightEvidence,
    roots: tuple[SearchRoot, ...],
    destination_directory: Path,
    destination_storage_class: RootStorageClass,
    limits: ReferenceIOLimits = ASSET_DISCOVERY_IO_LIMITS,
) -> Path:
    """Copy one explicitly selected strong candidate and verify its hash."""
    if candidate.recommendation != "strong-candidate":
        raise ValueError("only strong candidates can be materialized")
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

    destination_root = AuthorizedRoot.create(
        destination_directory,
        label="asset destination root",
        root_alias="asset-destination",
        storage_class=destination_storage_class,
    )
    filename = candidate.materialized_filename
    state = destination_root.state(filename)
    destination = destination_root.child_path(filename)
    if state == "regular":
        try:
            source_observation = root_paths[candidate.root_alias].observe_file(
                relative,
                max_bytes=max_file_bytes,
            )
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        if (
            source_observation.sha256 != candidate.sha256
            or source_observation.byte_size != candidate.byte_size
        ):
            raise ValueError("candidate source hash changed after planning")
        destination_observation = destination_root.observe_file(
            filename,
            max_bytes=max_file_bytes,
        )
        if (
            destination_observation.sha256 == candidate.sha256
            and destination_observation.byte_size == candidate.byte_size
        ):
            return destination
        raise FileExistsError(
            f"destination exists with different bytes: {destination}"
        )
    if state != "missing":
        raise FileExistsError(f"destination is not a file: {destination}")
    try:
        return destination_root.copy_file_from(
            root_paths[candidate.root_alias],
            relative,
            filename,
            max_bytes=max_file_bytes,
            expected_sha256=candidate.sha256,
            expected_size=candidate.byte_size,
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    except PathSafetyError as error:
        if "source identity changed" in str(error):
            raise ValueError(
                "candidate source hash changed after planning"
            ) from error
        raise


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
