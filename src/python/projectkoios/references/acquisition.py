from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from projectkoios.references.assets import SearchRoot
from projectkoios.references.io_limits import (
    ACQUISITION_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_utf8_size,
    validate_json_text_nesting,
)
from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    FileObservation,
    PathLimitError,
    PlaceholderProbeSupport,
    RootPreflightEvidence,
    RootStorageClass,
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 4096
_IDENTITY_STATUSES = frozenset({"unaccepted-candidate"})


def _bounded(
    value: object,
    *,
    field: str,
    max_bytes: int = _MAX_TEXT,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or bounded_utf8_size(value, max_bytes=max_bytes) > max_bytes
    ):
        raise ValueError(f"{field} must be a bounded non-empty string")
    return value


def _relative_path(value: str) -> PurePosixPath:
    return validate_relative_path(value)


@dataclass(frozen=True)
class AcquisitionEntry:
    proposed_citekey: str
    root_alias: str
    relative_path: PurePosixPath
    sha256: str
    byte_size: int
    rights_status: str
    asset_status: str
    identity_status: str
    doi: str | None = None
    source_url: str | None = None
    source_version: str | None = None

    def __post_init__(self) -> None:
        validate_citekey(
            self.proposed_citekey,
            field="proposed_citekey",
        )
        _bounded(self.root_alias, field="root_alias")
        validate_root_alias(self.root_alias)
        if not isinstance(self.relative_path, PurePosixPath):
            raise ValueError("relative_path must be a portable path")
        _relative_path(self.relative_path.as_posix())
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(
            self.sha256
        ):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        if (
            isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or self.byte_size <= 0
        ):
            raise ValueError("byte_size must be a positive integer")
        _bounded(self.rights_status, field="rights_status")
        _bounded(self.asset_status, field="asset_status")
        if not isinstance(self.identity_status, str) or (
            self.identity_status not in _IDENTITY_STATUSES
        ):
            raise ValueError("unsupported identity_status")
        if self.doi is not None and not isinstance(self.doi, str):
            raise ValueError("doi must be a string or null")
        if normalize_doi(self.doi) != self.doi:
            raise ValueError("doi must be normalized")
        if self.source_url is not None:
            _bounded(self.source_url, field="source_url")
            parsed = urlparse(self.source_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("source_url must be an HTTP(S) URL")
        if self.source_version is not None:
            _bounded(self.source_version, field="source_version")

    @classmethod
    def from_dict(cls, value: object) -> AcquisitionEntry:
        if not isinstance(value, dict):
            raise ValueError("acquisition entry must be an object")
        expected = {
            "proposed_citekey",
            "root_alias",
            "relative_path",
            "sha256",
            "byte_size",
            "rights_status",
            "asset_status",
            "identity_status",
            "doi",
            "source_url",
            "source_version",
        }
        unknown = set(value) - expected
        if unknown:
            raise ValueError(
                f"unknown acquisition entry fields: {sorted(unknown)}"
            )
        required = expected - {"doi", "source_url", "source_version"}
        missing = required - set(value)
        if missing:
            raise ValueError(
                f"missing acquisition entry fields: {sorted(missing)}"
            )
        strings = {
            field: value[field]
            for field in required - {"byte_size", "relative_path"}
        }
        if not all(isinstance(item, str) for item in strings.values()):
            raise ValueError("acquisition entry string fields must be strings")
        for field in ("doi", "source_url", "source_version"):
            if value.get(field) is not None and not isinstance(
                value[field], str
            ):
                raise ValueError(f"{field} must be a string or null")
        if type(value["byte_size"]) is not int:
            raise ValueError("byte_size must be an integer")
        relative_path = value["relative_path"]
        if not isinstance(relative_path, str):
            raise ValueError("relative_path must be a string")
        return cls(
            proposed_citekey=value["proposed_citekey"],
            root_alias=value["root_alias"],
            relative_path=_relative_path(relative_path),
            sha256=value["sha256"],
            byte_size=value["byte_size"],
            rights_status=value["rights_status"],
            asset_status=value["asset_status"],
            identity_status=value["identity_status"],
            doi=value.get("doi"),
            source_url=value.get("source_url"),
            source_version=value.get("source_version"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "proposed_citekey": self.proposed_citekey,
            "root_alias": self.root_alias,
            "relative_path": self.relative_path.as_posix(),
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "rights_status": self.rights_status,
            "asset_status": self.asset_status,
            "identity_status": self.identity_status,
            "doi": self.doi,
            "source_url": self.source_url,
            "source_version": self.source_version,
        }


@dataclass(frozen=True)
class AcquisitionManifest:
    schema_version: int
    source_id: str
    coverage_status: str
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    root_preflights: tuple[RootPreflightEvidence, ...]
    entries: tuple[AcquisitionEntry, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 3:
            raise ValueError("unsupported acquisition-manifest schema version")
        if self.coverage_status != "complete":
            raise ValueError(
                "published acquisition manifests require complete coverage"
            )
        if self.effective_limits.profile != ACQUISITION_IO_LIMITS.profile:
            raise ValueError(
                "acquisition-manifest I/O-limit profile is incompatible"
            )
        if self.effective_limits_id != self.effective_limits.evidence_id:
            raise ValueError(
                "acquisition-manifest I/O-limit identity conflicts"
            )
        if not isinstance(self.root_preflights, tuple) or any(
            not isinstance(item, RootPreflightEvidence)
            for item in self.root_preflights
        ):
            raise ValueError("acquisition root preflights are invalid")
        root_aliases = tuple(item.root_alias for item in self.root_preflights)
        if root_aliases != tuple(sorted(root_aliases)) or len(
            root_aliases
        ) != len(set(root_aliases)):
            raise ValueError(
                "acquisition root preflights must be alias-sorted and unique"
            )
        _bounded(self.source_id, field="source_id")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("acquisition manifest must contain an entry tuple")
        if any(
            not isinstance(entry, AcquisitionEntry) for entry in self.entries
        ):
            raise ValueError("manifest entries must be AcquisitionEntry values")
        max_rows = self.effective_limits.max_rows
        if max_rows is None:
            raise ValueError("acquisition-manifest limits must define max_rows")
        if len(self.entries) > max_rows:
            raise ValueError("acquisition manifest exceeds the entry limit")
        citekeys = tuple(entry.proposed_citekey for entry in self.entries)
        sources = tuple(
            (entry.root_alias, entry.relative_path) for entry in self.entries
        )
        if len(citekeys) != len(set(citekeys)):
            raise ValueError("acquisition manifest contains duplicate citekeys")
        if len(sources) != len(set(sources)):
            raise ValueError(
                "acquisition manifest contains duplicate source paths"
            )
        if any(entry.root_alias not in root_aliases for entry in self.entries):
            raise ValueError("acquisition entry root has no preflight evidence")

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        limits: ReferenceIOLimits = ACQUISITION_IO_LIMITS,
    ) -> AcquisitionManifest:
        validate_json_text_nesting(
            text,
            limits=limits,
            resource="acquisition manifest JSON",
        )
        data = json.loads(text)
        _validate_json_depth(data, limits=limits)
        if not isinstance(data, dict):
            raise ValueError("acquisition manifest must be an object")
        expected_fields = {
            "schema_version",
            "source_id",
            "coverage_status",
            "effective_limits",
            "effective_limits_id",
            "root_preflights",
            "entries",
        }
        unknown = set(data) - expected_fields
        missing = expected_fields - set(data)
        if unknown or missing:
            raise ValueError(
                "acquisition-manifest fields differ: "
                f"missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        if type(data.get("schema_version")) is not int:
            raise ValueError("schema_version must be an integer")
        if not isinstance(data.get("source_id"), str):
            raise ValueError("source_id must be a string")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("entries must be an array")
        max_rows = _required_limit(limits.max_rows, "max_rows")
        if len(entries) > max_rows:
            raise ReferenceIOLimitError(
                resource="acquisition manifest",
                limit_name="max_rows",
                limit=max_rows,
                observed=len(entries),
                limits=limits,
            )
        limits_data = data.get("effective_limits")
        if not isinstance(limits_data, dict):
            raise ValueError("effective_limits must be an object")
        try:
            recorded_limits = ReferenceIOLimits(**limits_data)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "acquisition-manifest effective limits are malformed"
            ) from error
        coverage_status = data.get("coverage_status")
        effective_limits_id = data.get("effective_limits_id")
        if not isinstance(coverage_status, str) or not isinstance(
            effective_limits_id,
            str,
        ):
            raise ValueError("acquisition-manifest limit evidence is malformed")
        return cls(
            schema_version=data["schema_version"],
            source_id=data["source_id"],
            coverage_status=coverage_status,
            effective_limits=recorded_limits,
            effective_limits_id=effective_limits_id,
            root_preflights=_parse_root_preflights(data["root_preflights"]),
            entries=tuple(AcquisitionEntry.from_dict(item) for item in entries),
        )

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "source_id": self.source_id,
                    "coverage_status": self.coverage_status,
                    "effective_limits": self.effective_limits.to_dict(),
                    "effective_limits_id": self.effective_limits_id,
                    "root_preflights": [
                        {
                            "root_alias": item.root_alias,
                            "storage_class": item.storage_class.value,
                            "probe_id": item.probe_id,
                            "probe_support": (
                                None
                                if item.probe_support is None
                                else item.probe_support.value
                            ),
                        }
                        for item in self.root_preflights
                    ],
                    "entries": [entry.to_dict() for entry in self.entries],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


def create_acquisition_manifest(
    *,
    source_id: str,
    rows: tuple[dict[str, str], ...],
    roots: tuple[SearchRoot, ...],
    limits: ReferenceIOLimits = ACQUISITION_IO_LIMITS,
) -> AcquisitionManifest:
    max_rows = _required_limit(limits.max_rows, "max_rows")
    if len(rows) > max_rows:
        raise ReferenceIOLimitError(
            resource="acquisition rows",
            limit_name="max_rows",
            limit=max_rows,
            observed=len(rows),
            limits=limits,
        )
    max_text_bytes = _required_limit(limits.max_text_bytes, "max_text_bytes")
    root_paths = _resolved_roots(roots, limits=limits)
    entries: list[AcquisitionEntry] = []
    observed_sources: set[tuple[str, PurePosixPath]] = set()
    observed_citekeys: set[str] = set()
    total_bytes = 0
    required = {
        "proposed_citekey",
        "root_alias",
        "relative_path",
        "rights_status",
        "asset_status",
        "identity_status",
    }
    for index, row in enumerate(rows, start=2):
        missing = tuple(
            field for field in sorted(required) if not row.get(field)
        )
        if missing:
            raise ValueError(
                f"CSV row {index} is missing fields: {list(missing)}"
            )
        proposed_citekey = validate_citekey(
            row["proposed_citekey"],
            field="proposed_citekey",
        )
        if proposed_citekey in observed_citekeys:
            raise ValueError(f"CSV row {index} creates duplicate citekeys")
        observed_citekeys.add(proposed_citekey)
        root_alias = _bounded(
            row["root_alias"],
            field="root_alias",
            max_bytes=max_text_bytes,
        )
        validate_root_alias(root_alias)
        raw_relative_path = _bounded(
            row["relative_path"],
            field="relative_path",
            max_bytes=max_text_bytes,
        )
        relative_path = _relative_path(raw_relative_path)
        rights_status = _bounded(
            row["rights_status"],
            field="rights_status",
            max_bytes=max_text_bytes,
        )
        asset_status = _bounded(
            row["asset_status"],
            field="asset_status",
            max_bytes=max_text_bytes,
        )
        identity_status = _bounded(
            row["identity_status"],
            field="identity_status",
            max_bytes=max_text_bytes,
        )
        if identity_status not in _IDENTITY_STATUSES:
            raise ValueError("unsupported identity_status")
        raw_doi = row.get("doi") or None
        if raw_doi is not None:
            _bounded(raw_doi, field="doi", max_bytes=max_text_bytes)
        doi = normalize_doi(raw_doi)
        source_url = row.get("source_url") or None
        source_version = row.get("source_version") or None
        if source_url is not None:
            _bounded(
                source_url,
                field="source_url",
                max_bytes=max_text_bytes,
            )
            parsed_url = urlparse(source_url)
            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.netloc
            ):
                raise ValueError("source_url must be an HTTP(S) URL")
        if source_version is not None:
            _bounded(
                source_version,
                field="source_version",
                max_bytes=max_text_bytes,
            )
        source_identity = (root_alias, relative_path)
        if source_identity in observed_sources:
            raise ValueError(
                f"CSV row {index} duplicates an earlier source path"
            )
        observed_sources.add(source_identity)
        observation = _observe_source(
            root_alias,
            relative_path,
            root_paths,
            limits=limits,
        )
        if observation.prefix != b"%PDF-":
            raise ValueError(f"CSV row {index} source has no PDF header")
        entries.append(
            AcquisitionEntry(
                proposed_citekey=proposed_citekey,
                root_alias=root_alias,
                relative_path=relative_path,
                sha256=observation.sha256,
                byte_size=observation.byte_size,
                rights_status=rights_status,
                asset_status=asset_status,
                identity_status=identity_status,
                doi=doi,
                source_url=source_url,
                source_version=source_version,
            )
        )
        total_bytes += observation.byte_size
        max_total_bytes = _required_limit(
            limits.max_total_bytes,
            "max_total_bytes",
        )
        if total_bytes > max_total_bytes:
            raise ReferenceIOLimitError(
                resource="acquisition sources",
                limit_name="max_total_bytes",
                limit=max_total_bytes,
                observed=total_bytes,
                limits=limits,
            )
    return AcquisitionManifest(
        schema_version=3,
        source_id=source_id,
        coverage_status="complete",
        effective_limits=limits,
        effective_limits_id=limits.evidence_id,
        root_preflights=tuple(
            sorted(
                (root_paths[root.alias].preflight_evidence for root in roots),
                key=lambda item: item.root_alias,
            )
        ),
        entries=tuple(entries),
    )


def verify_acquisition_manifest(
    manifest: AcquisitionManifest,
    *,
    roots: tuple[SearchRoot, ...],
    limits: ReferenceIOLimits = ACQUISITION_IO_LIMITS,
) -> None:
    max_rows = _required_limit(limits.max_rows, "max_rows")
    if len(manifest.entries) > max_rows:
        raise ReferenceIOLimitError(
            resource="acquisition manifest entries",
            limit_name="max_rows",
            limit=max_rows,
            observed=len(manifest.entries),
            limits=limits,
        )
    root_paths = _resolved_roots(roots, limits=limits)
    supplied_preflights = tuple(
        sorted(
            (root_paths[root.alias].preflight_evidence for root in roots),
            key=lambda item: item.root_alias,
        )
    )
    if supplied_preflights != manifest.root_preflights:
        raise ValueError("acquisition root preflight evidence changed")
    total_bytes = 0
    for entry in manifest.entries:
        observation = _observe_source(
            entry.root_alias,
            entry.relative_path,
            root_paths,
            limits=limits,
        )
        if observation.prefix != b"%PDF-":
            raise ValueError(
                f"source has no PDF header: {entry.proposed_citekey}"
            )
        if observation.byte_size != entry.byte_size:
            raise ValueError(f"source size changed: {entry.proposed_citekey}")
        if observation.sha256 != entry.sha256:
            raise ValueError(f"source hash changed: {entry.proposed_citekey}")
        total_bytes += observation.byte_size
        max_total_bytes = _required_limit(
            limits.max_total_bytes,
            "max_total_bytes",
        )
        if total_bytes > max_total_bytes:
            raise ReferenceIOLimitError(
                resource="acquisition sources",
                limit_name="max_total_bytes",
                limit=max_total_bytes,
                observed=total_bytes,
                limits=limits,
            )


def _resolved_roots(
    roots: tuple[SearchRoot, ...],
    *,
    limits: ReferenceIOLimits,
) -> dict[str, AuthorizedRoot]:
    if not roots:
        raise ValueError("at least one source root is required")
    max_files = _required_limit(limits.max_files, "max_files")
    if len(roots) > max_files:
        raise ReferenceIOLimitError(
            resource="acquisition source roots",
            limit_name="max_files",
            limit=max_files,
            observed=len(roots),
            limits=limits,
        )
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("source-root aliases must be unique")
    resolved: dict[str, AuthorizedRoot] = {}
    for root in roots:
        resolved[root.alias] = AuthorizedRoot.existing(
            root.path,
            label=f"source root {root.alias!r}",
            root_alias=root.alias,
            storage_class=root.storage_class,
            placeholder_probe=root.placeholder_probe,
        )
    return resolved


def _observe_source(
    root_alias: str,
    relative_path: PurePosixPath,
    roots: dict[str, AuthorizedRoot],
    *,
    limits: ReferenceIOLimits,
) -> FileObservation:
    if root_alias not in roots:
        raise ValueError(f"source root was not supplied: {root_alias}")
    max_file_bytes = _required_limit(
        limits.max_file_bytes,
        "max_file_bytes",
    )
    try:
        roots[root_alias].require_readable_file(relative_path)
        return roots[root_alias].observe_file(
            relative_path,
            max_bytes=max_file_bytes,
            prefix_bytes=5,
        )
    except FileNotFoundError as error:
        raise ValueError(
            f"source is not a regular file: {relative_path}"
        ) from error
    except PathLimitError as error:
        raise ReferenceIOLimitError(
            resource=error.resource,
            limit_name=error.limit_name,
            limit=error.limit,
            observed=error.observed,
            limits=limits,
        ) from error


def _parse_root_preflights(value: object) -> tuple[RootPreflightEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("root_preflights must be an array")
    expected = {
        "root_alias",
        "storage_class",
        "probe_id",
        "probe_support",
    }
    parsed: list[RootPreflightEvidence] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("acquisition root preflight is malformed")
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
            raise ValueError(
                "acquisition root preflight is malformed"
            ) from error
    return tuple(parsed)


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"acquisition I/O profile must define {name}")
    return value


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
                resource="acquisition manifest JSON",
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
                    resource="acquisition manifest JSON text",
                    limit_name="max_text_bytes",
                    limit=maximum_text,
                    observed=observed,
                    limits=limits,
                )
