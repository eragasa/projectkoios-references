from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Self

from projectkoios.references.io_limits import (
    PDF_CORPUS_DISCOVERY_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_utf8_size,
    validate_json_text_nesting,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    FilesystemBoundaryError,
    FilesystemInventoryIssue,
    FilesystemIssueKind,
    MacOSFileProviderPlaceholderProbe,
    PathLimitError,
    PathSafetyError,
    PlaceholderObservation,
    PlaceholderPreflightError,
    PlaceholderProbeSupport,
    PlaceholderStatus,
    RootPreflightEvidence,
    RootStorageClass,
    authorize_root_preflight,
    validate_relative_path,
    validate_root_alias,
)

PDF_CORPUS_DISCOVERY_SCHEMA_VERSION = 1
PDF_CORPUS_DISCOVERY_ARTIFACT_KIND = (
    "projectkoios.references.pdf-corpus-discovery-plan"
)
PDF_CORPUS_DISCOVERY_CONTRACT_ID = (
    "projectkoios.references.pdf-corpus-discovery"
)
PDF_CORPUS_DISCOVERY_CONTRACT_VERSION = "0.1.0"
PDF_CORPUS_DISCOVERY_CONTRACT_STATUS = "proposed"
PDF_CORPUS_DISCOVERY_GENERATOR_NAME = (
    "projectkoios-references-pdf-corpus-discovery"
)
PDF_CORPUS_DISCOVERY_GENERATOR_VERSION = "1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_ID = re.compile(r"^blob:sha256:[0-9a-f]{64}$")
_OBSERVATION_ID = re.compile(r"^pdf-source-observation:sha256:[0-9a-f]{64}$")
_PROBE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MAX_DURABLE_TEXT_BYTES = 4_096
_LIMIT_FIELDS = frozenset(item.name for item in fields(ReferenceIOLimits))


@dataclass(frozen=True)
class PdfCorpusRoot:
    """One explicitly authorized runtime root; its path is never serialized."""

    alias: str
    path: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = None

    def __post_init__(self) -> None:
        validate_root_alias(self.alias, field="PDF corpus root alias")
        if not isinstance(self.path, Path):
            raise ValueError("PDF corpus root path must be a Path")
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("PDF corpus root storage class must be explicit")
        if (
            self.storage_class is RootStorageClass.LOCAL
            and self.placeholder_probe is not None
        ):
            raise ValueError("local PDF corpus roots must not supply a probe")
        if isinstance(
            self.placeholder_probe,
            MacOSFileProviderPlaceholderProbe,
        ) and not self.placeholder_probe.matches_root_path(self.path):
            raise ValueError(
                "macOS File Provider probe is bound to a different root"
            )


class PdfSkipReason(StrEnum):
    """Why an object could not become an exact byte source observation."""

    ROOT_MISSING = "root-missing"
    MISSING = "missing"
    ACCESS_CONTROLLED = "access-controlled"
    UNREADABLE = "unreadable"
    UNSAFE_ROOT = "unsafe-root"
    SYMLINK = "symlink"
    UNSUPPORTED_OBJECT = "unsupported-object"
    FILESYSTEM_BOUNDARY = "filesystem-boundary"
    NONPORTABLE_NAME = "nonportable-name"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    AMBIGUOUS = "ambiguous"
    CHANGED_DURING_OBSERVATION = "changed-during-observation"
    ENTRY_LIMIT = "entry-limit"
    FILE_LIMIT = "file-limit"
    DEPTH_LIMIT = "depth-limit"
    FILE_SIZE_LIMIT = "file-size-limit"
    TOTAL_SIZE_LIMIT = "total-size-limit"
    PATH_LENGTH_LIMIT = "path-length-limit"


_LIMIT_REASONS = {
    PdfSkipReason.ENTRY_LIMIT: "max_entries",
    PdfSkipReason.FILE_LIMIT: "max_files",
    PdfSkipReason.DEPTH_LIMIT: "max_nesting_depth",
    PdfSkipReason.FILE_SIZE_LIMIT: "max_file_bytes",
    PdfSkipReason.TOTAL_SIZE_LIMIT: "max_total_bytes",
    PdfSkipReason.PATH_LENGTH_LIMIT: "max_text_bytes",
}


@dataclass(frozen=True)
class PdfSkippedObservation:
    """Privacy-reduced evidence that corpus coverage is incomplete."""

    root_alias: str
    relative_path: str | None
    storage_class: RootStorageClass
    probe_id: str
    reason: PdfSkipReason
    limit_name: str | None = None
    limit: int | None = None
    observed: int | None = None

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        if self.relative_path is not None:
            if not isinstance(self.relative_path, str):
                raise ValueError("skipped relative path must be a string")
            validate_relative_path(self.relative_path)
            if (
                bounded_utf8_size(
                    self.relative_path,
                    max_bytes=_MAX_DURABLE_TEXT_BYTES,
                )
                > _MAX_DURABLE_TEXT_BYTES
            ):
                raise ValueError("skipped relative path is too long")
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("skipped observation storage class is invalid")
        _validate_probe_id(self.probe_id)
        if not isinstance(self.reason, PdfSkipReason):
            raise ValueError("PDF skip reason is invalid")
        expected_name = _LIMIT_REASONS.get(self.reason)
        if expected_name is None:
            if any(
                value is not None
                for value in (self.limit_name, self.limit, self.observed)
            ):
                raise ValueError("non-limit skip carries limit evidence")
        elif (
            self.limit_name != expected_name
            or type(self.limit) is not int
            or type(self.observed) is not int
            or self.limit <= 0
            or self.observed <= self.limit
        ):
            raise ValueError("PDF corpus limit observation is invalid")
        if self.storage_class is RootStorageClass.LOCAL and self.reason in {
            PdfSkipReason.CLOUD_PLACEHOLDER,
            PdfSkipReason.UNSUPPORTED_PLATFORM,
        }:
            raise ValueError("local roots cannot report cloud-only states")


@dataclass(frozen=True)
class PdfSourceObservation:
    """Exact identity and PDF-header result for one ordinary regular file."""

    root_alias: str
    relative_path: str
    storage_class: RootStorageClass
    probe_id: str
    sha256: str
    byte_size: int
    pdf_header_valid: bool
    content_id: str
    observation_id: str

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        if not isinstance(self.relative_path, str):
            raise ValueError("PDF source relative path must be a string")
        relative = validate_relative_path(self.relative_path)
        if (
            bounded_utf8_size(
                self.relative_path,
                max_bytes=_MAX_DURABLE_TEXT_BYTES,
            )
            > _MAX_DURABLE_TEXT_BYTES
        ):
            raise ValueError("PDF source relative path is too long")
        if not relative.name.casefold().endswith(".pdf"):
            raise ValueError("PDF source path must have a .pdf extension")
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("PDF source storage class is invalid")
        _validate_probe_id(self.probe_id)
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("PDF source SHA-256 is invalid")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("PDF source byte size is invalid")
        if type(self.pdf_header_valid) is not bool:
            raise ValueError("PDF header validity must be a bool")
        if (
            _CONTENT_ID.fullmatch(self.content_id) is None
            or self.content_id != f"blob:sha256:{self.sha256}"
        ):
            raise ValueError("PDF source content identity conflicts")
        if _OBSERVATION_ID.fullmatch(self.observation_id) is None:
            raise ValueError("PDF source observation identity is invalid")
        expected = _stable_id(
            "pdf-source-observation",
            self._identity_payload(),
        )
        if self.observation_id != expected:
            raise ValueError("PDF source observation identity conflicts")

    def _identity_payload(self) -> dict[str, object]:
        return {
            "root_alias": self.root_alias,
            "relative_path": self.relative_path,
            "storage_class": self.storage_class,
            "probe_id": self.probe_id,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "pdf_header_valid": self.pdf_header_valid,
            "content_id": self.content_id,
        }

    @classmethod
    def create(
        cls,
        *,
        root_alias: str,
        relative_path: str,
        storage_class: RootStorageClass,
        probe_id: str,
        sha256: str,
        byte_size: int,
        pdf_header_valid: bool,
    ) -> Self:
        payload: dict[str, object] = {
            "root_alias": root_alias,
            "relative_path": relative_path,
            "storage_class": storage_class,
            "probe_id": probe_id,
            "sha256": sha256,
            "byte_size": byte_size,
            "pdf_header_valid": pdf_header_valid,
            "content_id": f"blob:sha256:{sha256}",
        }
        return cls(
            root_alias=root_alias,
            relative_path=relative_path,
            storage_class=storage_class,
            probe_id=probe_id,
            sha256=sha256,
            byte_size=byte_size,
            pdf_header_valid=pdf_header_valid,
            content_id=f"blob:sha256:{sha256}",
            observation_id=_stable_id("pdf-source-observation", payload),
        )

    @property
    def processable(self) -> bool:
        """Whether this byte-accessible extension candidate has a PDF header."""
        return self.pdf_header_valid


@dataclass(frozen=True)
class PdfCorpusDiscoveryPlan:
    """Canonical replayable PDF inventory independent of bibliography data."""

    schema_version: int
    artifact_kind: str
    contract_id: str
    contract_version: str
    contract_status: str
    generator_name: str
    generator_version: str
    coverage_status: str
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    root_preflights: tuple[RootPreflightEvidence, ...]
    skipped_observations: tuple[PdfSkippedObservation, ...]
    source_observations: tuple[PdfSourceObservation, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("PDF corpus schema version must be an integer")
        expected_scalars = (
            (self.schema_version, PDF_CORPUS_DISCOVERY_SCHEMA_VERSION),
            (self.artifact_kind, PDF_CORPUS_DISCOVERY_ARTIFACT_KIND),
            (self.contract_id, PDF_CORPUS_DISCOVERY_CONTRACT_ID),
            (self.contract_version, PDF_CORPUS_DISCOVERY_CONTRACT_VERSION),
            (self.contract_status, PDF_CORPUS_DISCOVERY_CONTRACT_STATUS),
            (self.generator_name, PDF_CORPUS_DISCOVERY_GENERATOR_NAME),
            (self.generator_version, PDF_CORPUS_DISCOVERY_GENERATOR_VERSION),
        )
        if any(actual != expected for actual, expected in expected_scalars):
            raise ValueError("PDF corpus discovery contract fields conflict")
        expected_coverage = (
            "incomplete" if self.skipped_observations else "complete"
        )
        if self.coverage_status != expected_coverage:
            raise ValueError("PDF corpus coverage status conflicts")
        if not isinstance(self.effective_limits, ReferenceIOLimits):
            raise ValueError("PDF corpus I/O profile is incompatible")
        _require_compatible_limits(self.effective_limits)
        if self.effective_limits_id != self.effective_limits.evidence_id:
            raise ValueError("PDF corpus I/O-limit identity conflicts")
        if (
            not isinstance(self.root_preflights, tuple)
            or not self.root_preflights
            or any(
                not isinstance(item, RootPreflightEvidence)
                for item in self.root_preflights
            )
        ):
            raise ValueError("PDF corpus root preflights must be a tuple")
        root_keys = tuple(item.root_alias for item in self.root_preflights)
        if root_keys != tuple(sorted(root_keys)) or len(root_keys) != len(
            set(root_keys)
        ):
            raise ValueError("PDF corpus root preflights are not canonical")
        roots = {item.root_alias: item for item in self.root_preflights}
        if not isinstance(self.skipped_observations, tuple) or any(
            not isinstance(item, PdfSkippedObservation)
            for item in self.skipped_observations
        ):
            raise ValueError("PDF skipped observations must be a tuple")
        skipped_keys = tuple(
            _skipped_key(item) for item in self.skipped_observations
        )
        if skipped_keys != tuple(sorted(skipped_keys)) or len(
            skipped_keys
        ) != len(set(skipped_keys)):
            raise ValueError("PDF skipped observations are not canonical")
        if not isinstance(self.source_observations, tuple) or any(
            not isinstance(item, PdfSourceObservation)
            for item in self.source_observations
        ):
            raise ValueError("PDF source observations must be a tuple")
        source_keys = tuple(
            _source_key(item) for item in self.source_observations
        )
        if (
            source_keys != tuple(sorted(source_keys))
            or len(source_keys) != len(set(source_keys))
            or len({item.observation_id for item in self.source_observations})
            != len(self.source_observations)
        ):
            raise ValueError("PDF source observations are not canonical")
        for item in self.skipped_observations:
            root = roots.get(item.root_alias)
            if (
                root is None
                or item.storage_class is not root.storage_class
                or item.probe_id != root.probe_id
            ):
                raise ValueError("PDF observation conflicts with root evidence")
        for source_item in self.source_observations:
            root = roots.get(source_item.root_alias)
            if (
                root is None
                or source_item.storage_class is not root.storage_class
                or source_item.probe_id != root.probe_id
            ):
                raise ValueError("PDF observation conflicts with root evidence")
        source_paths = {
            (item.root_alias, item.relative_path)
            for item in self.source_observations
        }
        skipped_paths = {
            (item.root_alias, item.relative_path)
            for item in self.skipped_observations
            if item.relative_path is not None
        }
        if source_paths & skipped_paths:
            raise ValueError("PDF path cannot be both sourced and skipped")
        for alias, root in roots.items():
            if (
                root.storage_class is not RootStorageClass.CLOUD_BACKED
                or root.probe_support is PlaceholderProbeSupport.SUPPORTED
            ):
                continue
            expected_reason = (
                PdfSkipReason.UNSUPPORTED_PLATFORM
                if root.probe_support
                is PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
                else PdfSkipReason.AMBIGUOUS
            )
            if any(
                item.root_alias == alias for item in self.source_observations
            ) or not any(
                item.root_alias == alias
                and item.relative_path is None
                and item.reason is expected_reason
                for item in self.skipped_observations
            ):
                raise ValueError(
                    "unsupported cloud root must remain typed incomplete"
                )
        max_files = _required_limit(
            self.effective_limits.max_files, "max_files"
        )
        max_file_bytes = _required_limit(
            self.effective_limits.max_file_bytes,
            "max_file_bytes",
        )
        max_total_bytes = _required_limit(
            self.effective_limits.max_total_bytes,
            "max_total_bytes",
        )
        max_entries = _required_limit(
            self.effective_limits.max_entries,
            "max_entries",
        )
        max_observations = _required_limit(
            self.effective_limits.max_candidates,
            "max_candidates",
        )
        for source_item in self.source_observations:
            _validate_relative_path_limits(
                source_item.relative_path,
                limits=self.effective_limits,
                resource="PDF source relative path",
            )
        for skipped_item in self.skipped_observations:
            if skipped_item.relative_path is not None:
                _validate_relative_path_limits(
                    skipped_item.relative_path,
                    limits=self.effective_limits,
                    resource="PDF skipped relative path",
                )
        if len(self.root_preflights) > max_entries:
            raise ValueError("PDF root count exceeds recorded limits")
        if (
            len(self.skipped_observations) + len(self.source_observations)
            > max_observations
        ):
            raise ValueError("PDF observation count exceeds recorded limits")
        if len(self.source_observations) > max_files:
            raise ValueError("PDF source count exceeds recorded limits")
        if any(
            item.byte_size > max_file_bytes for item in self.source_observations
        ):
            raise ValueError("PDF source size exceeds recorded limits")
        if sum(item.byte_size for item in self.source_observations) > (
            max_total_bytes
        ):
            raise ValueError("PDF source total exceeds recorded limits")

    @property
    def plan_id(self) -> str:
        return (
            "pdf-corpus-discovery-plan:sha256:"
            + hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
        )

    @property
    def processable_sources(self) -> tuple[PdfSourceObservation, ...]:
        return tuple(
            item for item in self.source_observations if item.processable
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

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        limits: ReferenceIOLimits = PDF_CORPUS_DISCOVERY_IO_LIMITS,
    ) -> Self:
        _require_compatible_limits(limits)
        validate_json_text_nesting(
            text,
            limits=limits,
            resource="PDF corpus discovery plan JSON",
        )
        value = json.loads(text)
        _validate_json_value(value, limits=limits)
        expected_fields = {
            "schema_version",
            "artifact_kind",
            "contract_id",
            "contract_version",
            "contract_status",
            "generator_name",
            "generator_version",
            "coverage_status",
            "effective_limits",
            "effective_limits_id",
            "root_preflights",
            "skipped_observations",
            "source_observations",
        }
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise ValueError("PDF corpus discovery plan fields are invalid")
        raw_limits = value["effective_limits"]
        if not isinstance(raw_limits, dict) or set(raw_limits) != _LIMIT_FIELDS:
            raise ValueError("PDF corpus effective limits are malformed")
        try:
            recorded_limits = ReferenceIOLimits(**raw_limits)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "PDF corpus effective limits are malformed"
            ) from error
        root_values = value["root_preflights"]
        skipped_values = value["skipped_observations"]
        source_values = value["source_observations"]
        if not all(
            isinstance(item, list)
            for item in (root_values, skipped_values, source_values)
        ):
            raise ValueError("PDF corpus observation arrays are malformed")
        max_entries = _required_limit(limits.max_entries, "max_entries")
        max_observations = _required_limit(
            limits.max_candidates,
            "max_candidates",
        )
        if len(root_values) > max_entries:
            raise ReferenceIOLimitError(
                resource="PDF corpus roots",
                limit_name="max_entries",
                limit=max_entries,
                observed=len(root_values),
                limits=limits,
            )
        if len(skipped_values) + len(source_values) > max_observations:
            raise ReferenceIOLimitError(
                resource="PDF corpus observations",
                limit_name="max_candidates",
                limit=max_observations,
                observed=len(skipped_values) + len(source_values),
                limits=limits,
            )
        plan = cls(
            schema_version=value["schema_version"],
            artifact_kind=value["artifact_kind"],
            contract_id=value["contract_id"],
            contract_version=value["contract_version"],
            contract_status=value["contract_status"],
            generator_name=value["generator_name"],
            generator_version=value["generator_version"],
            coverage_status=value["coverage_status"],
            effective_limits=recorded_limits,
            effective_limits_id=value["effective_limits_id"],
            root_preflights=_parse_root_preflights(root_values),
            skipped_observations=_parse_skipped(skipped_values),
            source_observations=_parse_sources(source_values),
        )
        if text != plan.to_json():
            raise ValueError("PDF corpus discovery plan JSON is noncanonical")
        return plan


@dataclass(frozen=True)
class ReboundPdfSource:
    """Runtime-only exact source binding for safe application composition."""

    source: PdfSourceObservation
    root: AuthorizedRoot
    relative_path: PurePosixPath

    def __post_init__(self) -> None:
        if not isinstance(self.source, PdfSourceObservation):
            raise ValueError("rebound PDF source observation is invalid")
        if not isinstance(self.root, AuthorizedRoot):
            raise ValueError("rebound PDF root is invalid")
        if validate_relative_path(self.relative_path).as_posix() != (
            self.source.relative_path
        ):
            raise ValueError("rebound PDF relative path conflicts")


def discover_pdf_corpus(
    roots: tuple[PdfCorpusRoot, ...],
    *,
    limits: ReferenceIOLimits = PDF_CORPUS_DISCOVERY_IO_LIMITS,
) -> PdfCorpusDiscoveryPlan:
    """Discover exact PDF extension candidates within explicit roots.

    Inventory is deterministic and metadata-only.  Every cloud candidate is
    preflighted before its bytes are observed.  Skips make coverage incomplete
    but remain replayable rather than being interpreted as absence.
    """
    _require_compatible_limits(limits)
    if not isinstance(roots, tuple) or not roots:
        raise ValueError("at least one PDF corpus root is required")
    if any(not isinstance(root, PdfCorpusRoot) for root in roots):
        raise ValueError("PDF corpus roots must be PdfCorpusRoot values")
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("PDF corpus root aliases must be unique")
    _reject_declared_root_overlaps(roots)
    max_entries = _required_limit(limits.max_entries, "max_entries")
    if len(roots) > max_entries:
        raise ReferenceIOLimitError(
            resource="PDF corpus roots",
            limit_name="max_entries",
            limit=max_entries,
            observed=len(roots),
            limits=limits,
        )
    max_files = _required_limit(limits.max_files, "max_files")
    max_depth = _required_limit(
        limits.max_nesting_depth,
        "max_nesting_depth",
    )
    max_text = _required_limit(limits.max_text_bytes, "max_text_bytes")
    ordered_roots = tuple(sorted(roots, key=lambda item: item.alias))
    root_evidence: list[RootPreflightEvidence] = []
    skipped: list[PdfSkippedObservation] = []
    bound: dict[str, AuthorizedRoot] = {}
    for root in ordered_roots:
        evidence, safe_root, failure = _bind_root(root)
        root_evidence.append(evidence)
        if failure is not None:
            skipped.append(failure)
        elif safe_root is not None:
            bound[root.alias] = safe_root
    _reject_bound_root_overlaps(bound)

    candidates: list[tuple[str, PurePosixPath]] = []
    remaining_entries = max_entries
    remaining_files = max_files
    terminal_limit: tuple[PdfSkipReason, str, int, int] | None = None
    for root in ordered_roots:
        safe_root = bound.get(root.alias)
        if safe_root is None:
            continue
        evidence = safe_root.preflight_evidence
        if terminal_limit is not None:
            reason, name, limit, observed = terminal_limit
            skipped.append(
                PdfSkippedObservation(
                    root.alias,
                    None,
                    root.storage_class,
                    evidence.probe_id,
                    reason,
                    name,
                    limit,
                    observed,
                )
            )
            continue
        if remaining_entries <= 0:
            terminal_limit = (
                PdfSkipReason.ENTRY_LIMIT,
                "max_entries",
                max_entries,
                max_entries + 1,
            )
            skipped.append(
                PdfSkippedObservation(
                    root.alias,
                    None,
                    root.storage_class,
                    evidence.probe_id,
                    *terminal_limit,
                )
            )
            continue
        if remaining_files <= 0:
            terminal_limit = (
                PdfSkipReason.FILE_LIMIT,
                "max_files",
                max_files,
                max_files + 1,
            )
            skipped.append(
                PdfSkippedObservation(
                    root.alias,
                    None,
                    root.storage_class,
                    evidence.probe_id,
                    *terminal_limit,
                )
            )
            continue
        try:
            inventory = safe_root.inventory_files(
                suffix=".pdf",
                recursive=True,
                max_files=remaining_files,
                max_entries=remaining_entries,
                max_depth=max_depth,
                case_sensitive_suffix=False,
            )
        except PermissionError:
            skipped.append(
                _root_skip(
                    root,
                    evidence,
                    PdfSkipReason.ACCESS_CONTROLLED,
                )
            )
            continue
        except PathSafetyError:
            skipped.append(
                _root_skip(root, evidence, PdfSkipReason.UNSAFE_ROOT)
            )
            continue
        except OSError:
            skipped.append(_root_skip(root, evidence, PdfSkipReason.UNREADABLE))
            continue
        remaining_entries = max(0, remaining_entries - inventory.entries_seen)
        remaining_files = max(0, remaining_files - len(inventory.files))
        for issue in inventory.issues:
            skip_observation = _inventory_skip(
                issue,
                evidence=evidence,
                limits=limits,
                max_text=max_text,
            )
            skipped.append(skip_observation)
            if issue.kind is FilesystemIssueKind.ENTRY_LIMIT:
                terminal_limit = (
                    PdfSkipReason.ENTRY_LIMIT,
                    "max_entries",
                    max_entries,
                    max_entries + 1,
                )
            elif issue.kind is FilesystemIssueKind.FILE_LIMIT:
                terminal_limit = (
                    PdfSkipReason.FILE_LIMIT,
                    "max_files",
                    max_files,
                    max_files + 1,
                )
                remaining_files = 0
        for relative in inventory.files:
            rendered = relative.as_posix()
            path_size = bounded_utf8_size(rendered, max_bytes=max_text)
            if path_size > max_text:
                skipped.append(
                    PdfSkippedObservation(
                        root.alias,
                        None,
                        root.storage_class,
                        evidence.probe_id,
                        PdfSkipReason.PATH_LENGTH_LIMIT,
                        "max_text_bytes",
                        max_text,
                        path_size,
                    )
                )
                continue
            candidates.append((root.alias, relative))

    max_file_bytes = _required_limit(limits.max_file_bytes, "max_file_bytes")
    max_total_bytes = _required_limit(
        limits.max_total_bytes,
        "max_total_bytes",
    )
    observed_bytes = 0
    sources: list[PdfSourceObservation] = []
    for alias, relative in sorted(
        candidates,
        key=lambda item: (item[0], item[1].as_posix()),
    ):
        safe_root = bound[alias]
        evidence = safe_root.preflight_evidence
        try:
            preflight = safe_root.preflight_file(relative)
        except FileNotFoundError:
            skipped.append(
                _simple_skip(evidence, relative, PdfSkipReason.MISSING)
            )
            continue
        except PermissionError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.ACCESS_CONTROLLED,
                )
            )
            continue
        except FilesystemBoundaryError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.FILESYSTEM_BOUNDARY,
                )
            )
            continue
        except PathSafetyError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.CHANGED_DURING_OBSERVATION,
                )
            )
            continue
        except OSError:
            skipped.append(
                _simple_skip(evidence, relative, PdfSkipReason.UNREADABLE)
            )
            continue
        if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
            skipped.append(_placeholder_skip(preflight))
            continue
        remaining_bytes = max_total_bytes - observed_bytes
        if remaining_bytes <= 0:
            skipped.append(
                PdfSkippedObservation(
                    alias,
                    relative.as_posix(),
                    evidence.storage_class,
                    evidence.probe_id,
                    PdfSkipReason.TOTAL_SIZE_LIMIT,
                    "max_total_bytes",
                    max_total_bytes,
                    max_total_bytes + 1,
                )
            )
            continue
        observation_limit = min(max_file_bytes, remaining_bytes)
        try:
            file_observation = safe_root.observe_file(
                relative,
                max_bytes=observation_limit,
                prefix_bytes=5,
            )
        except PlaceholderPreflightError as error:
            skipped.append(_placeholder_skip(error.observation))
            continue
        except PathLimitError as error:
            if error.observed > max_file_bytes:
                skipped.append(
                    PdfSkippedObservation(
                        alias,
                        relative.as_posix(),
                        evidence.storage_class,
                        evidence.probe_id,
                        PdfSkipReason.FILE_SIZE_LIMIT,
                        "max_file_bytes",
                        max_file_bytes,
                        error.observed,
                    )
                )
            else:
                skipped.append(
                    PdfSkippedObservation(
                        alias,
                        relative.as_posix(),
                        evidence.storage_class,
                        evidence.probe_id,
                        PdfSkipReason.TOTAL_SIZE_LIMIT,
                        "max_total_bytes",
                        max_total_bytes,
                        observed_bytes + error.observed,
                    )
                )
            continue
        except FileNotFoundError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.MISSING,
                )
            )
            continue
        except PermissionError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.ACCESS_CONTROLLED,
                )
            )
            continue
        except FilesystemBoundaryError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.FILESYSTEM_BOUNDARY,
                )
            )
            continue
        except PathSafetyError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.CHANGED_DURING_OBSERVATION,
                )
            )
            continue
        except OSError:
            skipped.append(
                _simple_skip(
                    evidence,
                    relative,
                    PdfSkipReason.UNREADABLE,
                )
            )
            continue
        observed_bytes += file_observation.byte_size
        sources.append(
            PdfSourceObservation.create(
                root_alias=alias,
                relative_path=relative.as_posix(),
                storage_class=evidence.storage_class,
                probe_id=evidence.probe_id,
                sha256=file_observation.sha256,
                byte_size=file_observation.byte_size,
                pdf_header_valid=file_observation.prefix == b"%PDF-",
            )
        )

    ordered_skipped = tuple(sorted(set(skipped), key=_skipped_key))
    ordered_sources = tuple(sorted(sources, key=_source_key))
    max_observations = _required_limit(
        limits.max_candidates,
        "max_candidates",
    )
    observation_count = len(ordered_skipped) + len(ordered_sources)
    if observation_count > max_observations:
        raise ReferenceIOLimitError(
            resource="PDF corpus observations",
            limit_name="max_candidates",
            limit=max_observations,
            observed=observation_count,
            limits=limits,
        )
    plan = PdfCorpusDiscoveryPlan(
        schema_version=PDF_CORPUS_DISCOVERY_SCHEMA_VERSION,
        artifact_kind=PDF_CORPUS_DISCOVERY_ARTIFACT_KIND,
        contract_id=PDF_CORPUS_DISCOVERY_CONTRACT_ID,
        contract_version=PDF_CORPUS_DISCOVERY_CONTRACT_VERSION,
        contract_status=PDF_CORPUS_DISCOVERY_CONTRACT_STATUS,
        generator_name=PDF_CORPUS_DISCOVERY_GENERATOR_NAME,
        generator_version=PDF_CORPUS_DISCOVERY_GENERATOR_VERSION,
        coverage_status="incomplete" if skipped else "complete",
        effective_limits=limits,
        effective_limits_id=limits.evidence_id,
        root_preflights=tuple(
            sorted(root_evidence, key=lambda item: item.root_alias)
        ),
        skipped_observations=ordered_skipped,
        source_observations=ordered_sources,
    )
    validate_json_text_nesting(
        plan.to_json(),
        limits=limits,
        resource="PDF corpus discovery plan JSON",
    )
    return plan


def rebind_pdf_source(
    source: PdfSourceObservation,
    roots: tuple[PdfCorpusRoot, ...],
    *,
    limits: ReferenceIOLimits = PDF_CORPUS_DISCOVERY_IO_LIMITS,
) -> ReboundPdfSource:
    """Rebind and reobserve exact processable bytes before application use."""
    _require_compatible_limits(limits)
    if not isinstance(source, PdfSourceObservation) or not source.processable:
        raise ValueError("rebind requires a processable PDF source observation")
    if not isinstance(roots, tuple) or any(
        not isinstance(root, PdfCorpusRoot) for root in roots
    ):
        raise ValueError("PDF corpus roots must be PdfCorpusRoot values")
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("PDF corpus root aliases must be unique")
    _reject_declared_root_overlaps(roots)
    relative = validate_relative_path(source.relative_path)
    max_text = _required_limit(limits.max_text_bytes, "max_text_bytes")
    observed_text = bounded_utf8_size(relative.as_posix(), max_bytes=max_text)
    if observed_text > max_text:
        raise ReferenceIOLimitError(
            resource="PDF source rebind path",
            limit_name="max_text_bytes",
            limit=max_text,
            observed=observed_text,
            limits=limits,
        )
    max_depth = _required_limit(
        limits.max_nesting_depth,
        "max_nesting_depth",
    )
    directory_depth = max(0, len(relative.parts) - 1)
    if directory_depth > max_depth:
        raise ReferenceIOLimitError(
            resource="PDF source rebind path",
            limit_name="max_nesting_depth",
            limit=max_depth,
            observed=directory_depth,
            limits=limits,
        )
    max_file_bytes = _required_limit(limits.max_file_bytes, "max_file_bytes")
    max_total_bytes = _required_limit(
        limits.max_total_bytes,
        "max_total_bytes",
    )
    if source.byte_size > max_file_bytes:
        raise ReferenceIOLimitError(
            resource="PDF source rebind",
            limit_name="max_file_bytes",
            limit=max_file_bytes,
            observed=source.byte_size,
            limits=limits,
        )
    if source.byte_size > max_total_bytes:
        raise ReferenceIOLimitError(
            resource="PDF source rebind",
            limit_name="max_total_bytes",
            limit=max_total_bytes,
            observed=source.byte_size,
            limits=limits,
        )
    observation_limit = min(max_file_bytes, max_total_bytes)
    matches = tuple(root for root in roots if root.alias == source.root_alias)
    if len(matches) != 1:
        raise ValueError("PDF source root alias must resolve exactly once")
    declaration = matches[0]
    if declaration.storage_class is not source.storage_class:
        raise ValueError("PDF source storage declaration changed")
    safe_root = AuthorizedRoot.existing(
        declaration.path,
        label=f"PDF corpus root {declaration.alias!r}",
        root_alias=declaration.alias,
        storage_class=declaration.storage_class,
        placeholder_probe=declaration.placeholder_probe,
    )
    if safe_root.preflight_evidence.probe_id != source.probe_id:
        raise ValueError("PDF source placeholder probe changed")
    preflight = safe_root.preflight_file(relative)
    if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
        raise PlaceholderPreflightError(preflight)
    try:
        observed = safe_root.observe_file(
            relative,
            max_bytes=observation_limit,
            prefix_bytes=5,
        )
    except PathLimitError as error:
        if error.observed > max_file_bytes:
            limit_name = "max_file_bytes"
            limit = max_file_bytes
        else:
            limit_name = "max_total_bytes"
            limit = max_total_bytes
        raise ReferenceIOLimitError(
            resource=error.resource,
            limit_name=limit_name,
            limit=limit,
            observed=error.observed,
            limits=limits,
        ) from error
    if (
        observed.sha256 != source.sha256
        or observed.byte_size != source.byte_size
        or (observed.prefix == b"%PDF-") is not source.pdf_header_valid
    ):
        raise ValueError("PDF source identity changed after discovery")
    return ReboundPdfSource(source, safe_root, relative)


def _reject_declared_root_overlaps(
    roots: tuple[PdfCorpusRoot, ...],
) -> None:
    normalized = tuple(
        (root.alias, _path_parts_without_resolution(root.path))
        for root in roots
    )
    _reject_path_part_overlaps(normalized)


def _reject_bound_root_overlaps(
    roots: dict[str, AuthorizedRoot],
) -> None:
    normalized = tuple(
        (alias, _normalized_path_parts(root.path))
        for alias, root in roots.items()
    )
    _reject_path_part_overlaps(normalized)


def _reject_path_part_overlaps(
    roots: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    ordered = tuple(sorted(roots, key=lambda item: item[0]))
    for index, (left_alias, left) in enumerate(ordered):
        for right_alias, right in ordered[index + 1 :]:
            shorter = min(len(left), len(right))
            if left[:shorter] == right[:shorter]:
                raise ValueError(
                    "PDF corpus roots must not duplicate or overlap: "
                    f"{left_alias!r} and {right_alias!r}"
                )


def _path_parts_without_resolution(path: Path) -> tuple[str, ...]:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    return _normalized_path_parts(normalized)


def _normalized_path_parts(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _bind_root(
    root: PdfCorpusRoot,
) -> tuple[
    RootPreflightEvidence,
    AuthorizedRoot | None,
    PdfSkippedObservation | None,
]:
    try:
        evidence = authorize_root_preflight(
            root_alias=root.alias,
            storage_class=root.storage_class,
            placeholder_probe=root.placeholder_probe,
        )
    except PlaceholderPreflightError as error:
        observation = error.observation
        support = (
            PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
            if observation.status is PlaceholderStatus.UNSUPPORTED_PLATFORM
            else PlaceholderProbeSupport.AMBIGUOUS
        )
        evidence = RootPreflightEvidence(
            root_alias=root.alias,
            storage_class=root.storage_class,
            probe_id=observation.probe_id,
            probe_support=support,
        )
        return evidence, None, _placeholder_skip(observation)
    supplied = root.path.expanduser()
    try:
        metadata = os.stat(supplied, follow_symlinks=False)
    except FileNotFoundError:
        return (
            evidence,
            None,
            _root_skip(root, evidence, PdfSkipReason.ROOT_MISSING),
        )
    except PermissionError:
        return (
            evidence,
            None,
            _root_skip(
                root,
                evidence,
                PdfSkipReason.ACCESS_CONTROLLED,
            ),
        )
    except OSError:
        return (
            evidence,
            None,
            _root_skip(root, evidence, PdfSkipReason.UNREADABLE),
        )
    if stat.S_ISLNK(metadata.st_mode):
        return evidence, None, _root_skip(root, evidence, PdfSkipReason.SYMLINK)
    if not stat.S_ISDIR(metadata.st_mode):
        return (
            evidence,
            None,
            _root_skip(
                root,
                evidence,
                PdfSkipReason.UNSUPPORTED_OBJECT,
            ),
        )
    try:
        safe_root = AuthorizedRoot.existing(
            supplied,
            label=f"PDF corpus root {root.alias!r}",
            root_alias=root.alias,
            storage_class=root.storage_class,
            placeholder_probe=root.placeholder_probe,
        )
    except PlaceholderPreflightError as error:
        observation = error.observation
        changed_evidence = RootPreflightEvidence(
            root_alias=root.alias,
            storage_class=root.storage_class,
            probe_id=observation.probe_id,
            probe_support=(
                PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
                if observation.status is PlaceholderStatus.UNSUPPORTED_PLATFORM
                else PlaceholderProbeSupport.AMBIGUOUS
            ),
        )
        return changed_evidence, None, _placeholder_skip(observation)
    except FileNotFoundError:
        return (
            evidence,
            None,
            _root_skip(root, evidence, PdfSkipReason.ROOT_MISSING),
        )
    except PermissionError:
        return (
            evidence,
            None,
            _root_skip(
                root,
                evidence,
                PdfSkipReason.ACCESS_CONTROLLED,
            ),
        )
    except PathSafetyError:
        return (
            evidence,
            None,
            _root_skip(root, evidence, PdfSkipReason.UNSAFE_ROOT),
        )
    except OSError:
        return (
            evidence,
            None,
            _root_skip(root, evidence, PdfSkipReason.UNREADABLE),
        )
    if safe_root.preflight_evidence != evidence:
        return (
            evidence,
            None,
            _root_skip(root, evidence, PdfSkipReason.AMBIGUOUS),
        )
    return evidence, safe_root, None


def _root_skip(
    root: PdfCorpusRoot,
    evidence: RootPreflightEvidence,
    reason: PdfSkipReason,
) -> PdfSkippedObservation:
    return PdfSkippedObservation(
        root.alias,
        None,
        root.storage_class,
        evidence.probe_id,
        reason,
    )


def _simple_skip(
    evidence: RootPreflightEvidence,
    relative: PurePosixPath,
    reason: PdfSkipReason,
) -> PdfSkippedObservation:
    return PdfSkippedObservation(
        evidence.root_alias,
        relative.as_posix(),
        evidence.storage_class,
        evidence.probe_id,
        reason,
    )


def _inventory_skip(
    issue: FilesystemInventoryIssue,
    *,
    evidence: RootPreflightEvidence,
    limits: ReferenceIOLimits,
    max_text: int,
) -> PdfSkippedObservation:
    mapping = {
        FilesystemIssueKind.ACCESS_CONTROLLED: PdfSkipReason.ACCESS_CONTROLLED,
        FilesystemIssueKind.UNREADABLE: PdfSkipReason.UNREADABLE,
        FilesystemIssueKind.SYMLINK: PdfSkipReason.SYMLINK,
        FilesystemIssueKind.UNSUPPORTED_OBJECT: (
            PdfSkipReason.UNSUPPORTED_OBJECT
        ),
        FilesystemIssueKind.FILESYSTEM_BOUNDARY: (
            PdfSkipReason.FILESYSTEM_BOUNDARY
        ),
        FilesystemIssueKind.NONPORTABLE_NAME: PdfSkipReason.NONPORTABLE_NAME,
        FilesystemIssueKind.ENTRY_LIMIT: PdfSkipReason.ENTRY_LIMIT,
        FilesystemIssueKind.FILE_LIMIT: PdfSkipReason.FILE_LIMIT,
        FilesystemIssueKind.DEPTH_LIMIT: PdfSkipReason.DEPTH_LIMIT,
    }
    reason = mapping[issue.kind]
    relative = (
        None if issue.relative_path is None else issue.relative_path.as_posix()
    )
    if (
        relative is not None
        and bounded_utf8_size(
            relative,
            max_bytes=max_text,
        )
        > max_text
    ):
        relative = None
    if reason is PdfSkipReason.DEPTH_LIMIT:
        limit_name = "max_nesting_depth"
        limit = _required_limit(limits.max_nesting_depth, limit_name)
        observed = issue.observed
    elif reason in {PdfSkipReason.ENTRY_LIMIT, PdfSkipReason.FILE_LIMIT}:
        limit_name = _LIMIT_REASONS[reason]
        limit = _required_limit(getattr(limits, limit_name), limit_name)
        observed = limit + 1
    else:
        limit_name = None
        limit = None
        observed = None
    return PdfSkippedObservation(
        evidence.root_alias,
        relative,
        evidence.storage_class,
        evidence.probe_id,
        reason,
        limit_name,
        limit,
        observed,
    )


def _placeholder_skip(
    observation: PlaceholderObservation,
) -> PdfSkippedObservation:
    if not isinstance(observation, PlaceholderObservation):
        raise TypeError("placeholder observation is invalid")
    reasons = {
        PlaceholderStatus.CLOUD_PLACEHOLDER: PdfSkipReason.CLOUD_PLACEHOLDER,
        PlaceholderStatus.MISSING: PdfSkipReason.MISSING,
        PlaceholderStatus.ACCESS_CONTROLLED: PdfSkipReason.ACCESS_CONTROLLED,
        PlaceholderStatus.UNREADABLE: PdfSkipReason.UNREADABLE,
        PlaceholderStatus.UNSUPPORTED_PLATFORM: (
            PdfSkipReason.UNSUPPORTED_PLATFORM
        ),
        PlaceholderStatus.AMBIGUOUS: PdfSkipReason.AMBIGUOUS,
        PlaceholderStatus.FILESYSTEM_BOUNDARY: (
            PdfSkipReason.FILESYSTEM_BOUNDARY
        ),
    }
    reason = reasons.get(observation.status)
    if reason is None:
        raise ValueError("ordinary placeholder status cannot be skipped")
    return PdfSkippedObservation(
        observation.root_alias,
        observation.relative_path,
        observation.storage_class,
        observation.probe_id,
        reason,
    )


def _parse_root_preflights(value: object) -> tuple[RootPreflightEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("PDF root preflights must be an array")
    expected = {"root_alias", "storage_class", "probe_id", "probe_support"}
    parsed: list[RootPreflightEvidence] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("PDF root preflight is malformed")
        try:
            raw_support = item["probe_support"]
            parsed.append(
                RootPreflightEvidence(
                    root_alias=item["root_alias"],
                    storage_class=RootStorageClass(item["storage_class"]),
                    probe_id=item["probe_id"],
                    probe_support=(
                        None
                        if raw_support is None
                        else PlaceholderProbeSupport(raw_support)
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError("PDF root preflight is malformed") from error
    return tuple(parsed)


def _parse_skipped(value: object) -> tuple[PdfSkippedObservation, ...]:
    if not isinstance(value, list):
        raise ValueError("PDF skipped observations must be an array")
    expected = {
        "root_alias",
        "relative_path",
        "storage_class",
        "probe_id",
        "reason",
        "limit_name",
        "limit",
        "observed",
    }
    parsed: list[PdfSkippedObservation] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("PDF skipped observation is malformed")
        try:
            parsed.append(
                PdfSkippedObservation(
                    root_alias=item["root_alias"],
                    relative_path=item["relative_path"],
                    storage_class=RootStorageClass(item["storage_class"]),
                    probe_id=item["probe_id"],
                    reason=PdfSkipReason(item["reason"]),
                    limit_name=item["limit_name"],
                    limit=item["limit"],
                    observed=item["observed"],
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError("PDF skipped observation is malformed") from error
    return tuple(parsed)


def _parse_sources(value: object) -> tuple[PdfSourceObservation, ...]:
    if not isinstance(value, list):
        raise ValueError("PDF source observations must be an array")
    expected = {
        "root_alias",
        "relative_path",
        "storage_class",
        "probe_id",
        "sha256",
        "byte_size",
        "pdf_header_valid",
        "content_id",
        "observation_id",
    }
    parsed: list[PdfSourceObservation] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("PDF source observation is malformed")
        try:
            parsed.append(
                PdfSourceObservation(
                    root_alias=item["root_alias"],
                    relative_path=item["relative_path"],
                    storage_class=RootStorageClass(item["storage_class"]),
                    probe_id=item["probe_id"],
                    sha256=item["sha256"],
                    byte_size=item["byte_size"],
                    pdf_header_valid=item["pdf_header_valid"],
                    content_id=item["content_id"],
                    observation_id=item["observation_id"],
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError("PDF source observation is malformed") from error
    return tuple(parsed)


def _source_key(item: PdfSourceObservation) -> tuple[str, str, str]:
    return item.root_alias, item.relative_path, item.observation_id


def _skipped_key(
    item: PdfSkippedObservation,
) -> tuple[str, str, str, str, int, int]:
    return (
        item.root_alias,
        item.relative_path or "",
        item.reason.value,
        item.limit_name or "",
        item.limit or 0,
        item.observed or 0,
    )


def _stable_id(kind: str, value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(payload).hexdigest()}"


def _validate_relative_path_limits(
    relative_path: str | PurePosixPath,
    *,
    limits: ReferenceIOLimits,
    resource: str,
) -> PurePosixPath:
    safe = validate_relative_path(relative_path)
    max_text = _required_limit(limits.max_text_bytes, "max_text_bytes")
    observed_text = bounded_utf8_size(safe.as_posix(), max_bytes=max_text)
    if observed_text > max_text:
        raise ValueError(f"{resource} exceeds recorded max_text_bytes")
    max_depth = _required_limit(
        limits.max_nesting_depth,
        "max_nesting_depth",
    )
    directory_depth = max(0, len(safe.parts) - 1)
    if directory_depth > max_depth:
        raise ValueError(f"{resource} exceeds recorded max_nesting_depth")
    return safe


def _validate_probe_id(value: object) -> str:
    if not isinstance(value, str) or _PROBE_ID.fullmatch(value) is None:
        raise ValueError("placeholder probe identity is invalid")
    return value


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"PDF corpus I/O profile must define {name}")
    return value


def _require_compatible_limits(limits: ReferenceIOLimits) -> None:
    if (
        not isinstance(limits, ReferenceIOLimits)
        or limits.profile != PDF_CORPUS_DISCOVERY_IO_LIMITS.profile
    ):
        raise ValueError("PDF corpus discovery I/O profile is incompatible")
    for name in (
        "max_files",
        "max_file_bytes",
        "max_total_bytes",
        "max_json_bytes",
        "max_json_depth",
        "max_nesting_depth",
        "max_text_bytes",
        "max_candidates",
        "max_entries",
    ):
        value = _required_limit(getattr(limits, name), name)
        default = _required_limit(
            getattr(PDF_CORPUS_DISCOVERY_IO_LIMITS, name),
            name,
        )
        if value > default:
            raise ValueError(f"PDF corpus {name} may only be tightened")


def _validate_json_value(
    value: object,
    *,
    limits: ReferenceIOLimits,
) -> None:
    max_depth = _required_limit(limits.max_json_depth, "max_json_depth")
    max_text = _required_limit(limits.max_text_bytes, "max_text_bytes")
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            raise ReferenceIOLimitError(
                resource="PDF corpus discovery plan JSON",
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
            observed = bounded_utf8_size(item, max_bytes=max_text)
            if observed > max_text:
                raise ReferenceIOLimitError(
                    resource="PDF corpus discovery plan JSON text",
                    limit_name="max_text_bytes",
                    limit=max_text,
                    observed=observed,
                    limits=limits,
                )
