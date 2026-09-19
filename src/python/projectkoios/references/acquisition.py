from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast
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
    CloudPlaceholderProbe,
    FileObservation,
    PathLimitError,
    PlaceholderProbeSupport,
    RootPreflightEvidence,
    RootStorageClass,
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

ACQUISITION_MANIFEST_SCHEMA_VERSION = 4
ACQUISITION_ARTIFACT_KIND = "projectkoios.references.acquisition-manifest"
ACQUISITION_CONTRACT_ID = "projectkoios.references.acquisition-observation"
ACQUISITION_CONTRACT_VERSION = "0.1.0"
ACQUISITION_CONTRACT_STATUS = "proposed"
ACQUISITION_GENERATOR_NAME = "projectkoios-references-acquisition"
ACQUISITION_GENERATOR_VERSION = "1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_ID = re.compile(r"^acquisition-manifest:sha256:[0-9a-f]{64}$")
_INPUT_ID = re.compile(r"^acquisition-input:sha256:[0-9a-f]{64}$")
_MAX_TEXT = 4096
_IDENTITY_STATUS = "unaccepted-candidate"
_CITEKEY_STATUS = "proposed-noncanonical"
_MANUSCRIPT_STATUS = "not-assessed"
_OBSERVATION_BASES = frozenset(
    {"operator-assertion", "explicitly-not-assessed"}
)


class AcquisitionPublicationError(RuntimeError):
    """Raised when an immutable acquisition output cannot be published."""


@dataclass(frozen=True)
class AcquisitionObservation:
    """An acquisition assertion, not an independent legality decision."""

    status: str
    basis: str

    def __post_init__(self) -> None:
        _bounded(self.status, field="acquisition status")
        _validate_observation_basis(self.basis)
        if (
            self.basis == "explicitly-not-assessed"
            and self.status != "not-assessed"
        ):
            raise ValueError(
                "explicitly-not-assessed acquisition basis requires "
                "not-assessed status"
            )

    @classmethod
    def from_dict(cls, value: object) -> AcquisitionObservation:
        status, basis = _parse_observation(value, "acquisition observation")
        return cls(status=status, basis=basis)

    def to_dict(self) -> dict[str, str]:
        return {"basis": self.basis, "status": self.status}


@dataclass(frozen=True)
class AccessObservation:
    """A source-access assertion kept separate from acquisition and rights."""

    status: str
    basis: str

    def __post_init__(self) -> None:
        _bounded(self.status, field="access status")
        _validate_observation_basis(self.basis)
        if self.basis != "operator-assertion":
            raise ValueError("access observation requires operator assertion")

    @classmethod
    def from_dict(cls, value: object) -> AccessObservation:
        status, basis = _parse_observation(value, "access observation")
        return cls(status=status, basis=basis)

    def to_dict(self) -> dict[str, str]:
        return {"basis": self.basis, "status": self.status}


@dataclass(frozen=True)
class RightsObservation:
    """A rights assertion; hashing the source does not verify the assertion."""

    status: str
    basis: str

    def __post_init__(self) -> None:
        _bounded(self.status, field="rights status")
        _validate_observation_basis(self.basis)
        if self.basis != "operator-assertion":
            raise ValueError("rights observation requires operator assertion")

    @classmethod
    def from_dict(cls, value: object) -> RightsObservation:
        status, basis = _parse_observation(value, "rights observation")
        return cls(status=status, basis=basis)

    def to_dict(self) -> dict[str, str]:
        return {"basis": self.basis, "status": self.status}


@dataclass(frozen=True)
class AcquisitionEntry:
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    manuscript_status: str
    root_alias: str
    relative_path: PurePosixPath
    sha256: str
    byte_size: int
    acquisition: AcquisitionObservation
    access: AccessObservation
    rights: RightsObservation
    doi: str | None = None
    source_url: str | None = None
    source_version: str | None = None

    def __post_init__(self) -> None:
        validate_citekey(self.proposed_citekey, field="proposed_citekey")
        if self.identity_status != _IDENTITY_STATUS:
            raise ValueError("unsupported identity_status")
        if self.citekey_status != _CITEKEY_STATUS:
            raise ValueError("acquisition citekey must remain noncanonical")
        if self.manuscript_status != _MANUSCRIPT_STATUS:
            raise ValueError("acquisition cannot claim manuscript acceptance")
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
        if not isinstance(self.acquisition, AcquisitionObservation):
            raise ValueError("acquisition observation is invalid")
        if not isinstance(self.access, AccessObservation):
            raise ValueError("access observation is invalid")
        if not isinstance(self.rights, RightsObservation):
            raise ValueError("rights observation is invalid")
        if self.doi is not None and not isinstance(self.doi, str):
            raise ValueError("doi must be a string or null")
        if normalize_doi(self.doi) != self.doi:
            raise ValueError("doi must be normalized")
        if self.source_url is not None:
            _validate_source_url(self.source_url)
        if self.source_version is not None:
            _bounded(self.source_version, field="source_version")

    @property
    def source_content_id(self) -> str:
        return f"blob:sha256:{self.sha256}"

    @property
    def acquisition_status(self) -> str:
        return self.acquisition.status

    @property
    def access_status(self) -> str:
        return self.access.status

    @property
    def rights_status(self) -> str:
        return self.rights.status

    @property
    def asset_status(self) -> str:
        """Compatibility alias for the former conflated access field."""
        return self.access.status

    @classmethod
    def from_dict(cls, value: object) -> AcquisitionEntry:
        data = _exact_object(
            value,
            fields={
                "proposed_citekey",
                "identity_status",
                "citekey_status",
                "manuscript_status",
                "root_alias",
                "relative_path",
                "sha256",
                "byte_size",
                "acquisition_observation",
                "access_observation",
                "rights_observation",
                "doi",
                "source_url",
                "source_version",
            },
            label="acquisition entry",
        )
        string_fields = {
            "proposed_citekey",
            "identity_status",
            "citekey_status",
            "manuscript_status",
            "root_alias",
            "relative_path",
            "sha256",
        }
        if any(not isinstance(data[field], str) for field in string_fields):
            raise ValueError("acquisition entry string fields must be strings")
        if type(data["byte_size"]) is not int:
            raise ValueError("byte_size must be an integer")
        for field in ("doi", "source_url", "source_version"):
            if data[field] is not None and not isinstance(data[field], str):
                raise ValueError(f"{field} must be a string or null")
        return cls(
            proposed_citekey=cast(str, data["proposed_citekey"]),
            identity_status=cast(str, data["identity_status"]),
            citekey_status=cast(str, data["citekey_status"]),
            manuscript_status=cast(str, data["manuscript_status"]),
            root_alias=cast(str, data["root_alias"]),
            relative_path=_relative_path(cast(str, data["relative_path"])),
            sha256=cast(str, data["sha256"]),
            byte_size=cast(int, data["byte_size"]),
            acquisition=AcquisitionObservation.from_dict(
                data["acquisition_observation"]
            ),
            access=AccessObservation.from_dict(data["access_observation"]),
            rights=RightsObservation.from_dict(data["rights_observation"]),
            doi=cast(str | None, data["doi"]),
            source_url=cast(str | None, data["source_url"]),
            source_version=cast(str | None, data["source_version"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "access_observation": self.access.to_dict(),
            "acquisition_observation": self.acquisition.to_dict(),
            "byte_size": self.byte_size,
            "citekey_status": self.citekey_status,
            "doi": self.doi,
            "identity_status": self.identity_status,
            "manuscript_status": self.manuscript_status,
            "proposed_citekey": self.proposed_citekey,
            "relative_path": self.relative_path.as_posix(),
            "rights_observation": self.rights.to_dict(),
            "root_alias": self.root_alias,
            "sha256": self.sha256,
            "source_url": self.source_url,
            "source_version": self.source_version,
        }

    def normalized_input_dict(self) -> dict[str, object]:
        """Return normalized operator input, excluding observed source bytes."""
        value = self.to_dict()
        del value["byte_size"]
        del value["sha256"]
        return value


@dataclass(frozen=True)
class AcquisitionProjection:
    """Privacy-reduced typed evidence for reconciliation consumers."""

    contract_id: str
    contract_version: str
    contract_status: str
    manifest_id: str
    normalized_input_id: str
    source_id: str
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    manuscript_status: str
    source_content_id: str
    source_sha256: str
    source_byte_size: int
    root_alias: str
    relative_path: str
    acquisition: AcquisitionObservation
    access: AccessObservation
    rights: RightsObservation
    doi: str | None
    source_url: str | None
    source_version: str | None

    def __post_init__(self) -> None:
        if (
            self.contract_id != ACQUISITION_CONTRACT_ID
            or self.contract_version != ACQUISITION_CONTRACT_VERSION
            or self.contract_status != ACQUISITION_CONTRACT_STATUS
        ):
            raise ValueError("acquisition projection contract is incompatible")
        if not _MANIFEST_ID.fullmatch(self.manifest_id):
            raise ValueError(
                "acquisition projection manifest identity is invalid"
            )
        if not _INPUT_ID.fullmatch(self.normalized_input_id):
            raise ValueError("acquisition projection input identity is invalid")
        _validate_source_id(self.source_id)
        validate_citekey(self.proposed_citekey, field="proposed_citekey")
        if (
            self.identity_status != _IDENTITY_STATUS
            or self.citekey_status != _CITEKEY_STATUS
            or self.manuscript_status != _MANUSCRIPT_STATUS
        ):
            raise ValueError(
                "acquisition projection exceeds candidate authority"
            )
        if (
            not _SHA256.fullmatch(self.source_sha256)
            or self.source_content_id != f"blob:sha256:{self.source_sha256}"
            or type(self.source_byte_size) is not int
            or self.source_byte_size <= 0
        ):
            raise ValueError(
                "acquisition projection source identity is invalid"
            )
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if not isinstance(self.acquisition, AcquisitionObservation):
            raise ValueError("acquisition projection observation is invalid")
        if not isinstance(self.access, AccessObservation):
            raise ValueError("acquisition projection access is invalid")
        if not isinstance(self.rights, RightsObservation):
            raise ValueError("acquisition projection rights are invalid")
        if normalize_doi(self.doi) != self.doi:
            raise ValueError("acquisition projection DOI must be normalized")
        if self.source_url is not None:
            _validate_source_url(self.source_url)
        if self.source_version is not None:
            _bounded(self.source_version, field="source_version")


@dataclass(frozen=True)
class AcquisitionManifest:
    schema_version: int
    artifact_kind: str
    contract_id: str
    contract_version: str
    contract_status: str
    generator_name: str
    generator_version: str
    source_id: str
    normalized_input_id: str
    coverage_status: str
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    root_preflights: tuple[RootPreflightEvidence, ...]
    entries: tuple[AcquisitionEntry, ...]
    manifest_id: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != ACQUISITION_MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("unsupported acquisition-manifest schema version")
        if self.artifact_kind != ACQUISITION_ARTIFACT_KIND:
            raise ValueError("unsupported acquisition artifact kind")
        if (
            self.contract_id != ACQUISITION_CONTRACT_ID
            or self.contract_version != ACQUISITION_CONTRACT_VERSION
            or self.contract_status != ACQUISITION_CONTRACT_STATUS
        ):
            raise ValueError("unsupported acquisition contract identity")
        if (
            self.generator_name != ACQUISITION_GENERATOR_NAME
            or self.generator_version != ACQUISITION_GENERATOR_VERSION
        ):
            raise ValueError("unsupported acquisition generator identity")
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
        max_root_entries = _required_limit(
            self.effective_limits.max_entries,
            "max_entries",
        )
        if len(self.root_preflights) > max_root_entries:
            raise ReferenceIOLimitError(
                resource="acquisition source roots",
                limit_name="max_entries",
                limit=max_root_entries,
                observed=len(self.root_preflights),
                limits=self.effective_limits,
            )
        _validate_source_id(
            self.source_id,
            max_bytes=_required_limit(
                self.effective_limits.max_text_bytes,
                "max_text_bytes",
            ),
        )
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("acquisition manifest must contain an entry tuple")
        if any(
            not isinstance(entry, AcquisitionEntry) for entry in self.entries
        ):
            raise ValueError("manifest entries must be AcquisitionEntry values")
        if self.entries != tuple(sorted(self.entries, key=_entry_key)):
            raise ValueError(
                "acquisition entries must be deterministically sorted"
            )
        count_limits = (
            ("max_rows", self.effective_limits.max_rows),
            ("max_files", self.effective_limits.max_files),
            ("max_candidates", self.effective_limits.max_candidates),
            ("max_entries", self.effective_limits.max_entries),
        )
        for limit_name, raw_limit in count_limits:
            limit = _required_limit(raw_limit, limit_name)
            if len(self.entries) > limit:
                raise ReferenceIOLimitError(
                    resource="acquisition manifest entries",
                    limit_name=limit_name,
                    limit=limit,
                    observed=len(self.entries),
                    limits=self.effective_limits,
                )
        max_file_bytes = _required_limit(
            self.effective_limits.max_file_bytes,
            "max_file_bytes",
        )
        oversized = tuple(
            entry.byte_size
            for entry in self.entries
            if entry.byte_size > max_file_bytes
        )
        if oversized:
            raise ReferenceIOLimitError(
                resource="acquisition manifest source",
                limit_name="max_file_bytes",
                limit=max_file_bytes,
                observed=max(oversized),
                limits=self.effective_limits,
            )
        total_bytes = sum(entry.byte_size for entry in self.entries)
        max_total_bytes = _required_limit(
            self.effective_limits.max_total_bytes,
            "max_total_bytes",
        )
        if total_bytes > max_total_bytes:
            raise ReferenceIOLimitError(
                resource="acquisition manifest sources",
                limit_name="max_total_bytes",
                limit=max_total_bytes,
                observed=total_bytes,
                limits=self.effective_limits,
            )
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
        expected_input = _normalized_input_id(
            source_id=self.source_id,
            entries=self.entries,
        )
        if not _INPUT_ID.fullmatch(self.normalized_input_id):
            raise ValueError("normalized acquisition input identity is invalid")
        if self.normalized_input_id != expected_input:
            raise ValueError("normalized acquisition input identity conflicts")
        if not _MANIFEST_ID.fullmatch(self.manifest_id):
            raise ValueError("acquisition manifest identity is invalid")
        if self.manifest_id != self.identity_for(
            schema_version=self.schema_version,
            artifact_kind=self.artifact_kind,
            contract_id=self.contract_id,
            contract_version=self.contract_version,
            contract_status=self.contract_status,
            generator_name=self.generator_name,
            generator_version=self.generator_version,
            source_id=self.source_id,
            normalized_input_id=self.normalized_input_id,
            coverage_status=self.coverage_status,
            effective_limits=self.effective_limits,
            effective_limits_id=self.effective_limits_id,
            root_preflights=self.root_preflights,
            entries=self.entries,
        ):
            raise ValueError("acquisition manifest identity does not match")
        canonical_text = self.to_json()
        validate_json_text_nesting(
            canonical_text,
            limits=self.effective_limits,
            resource="acquisition manifest JSON",
        )
        _validate_json_depth(
            _manifest_dict(self, include_identity=True),
            limits=self.effective_limits,
        )

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
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(
                "acquisition manifest is not valid JSON"
            ) from error
        _validate_json_depth(value, limits=limits)
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "artifact_kind",
                "contract_id",
                "contract_version",
                "contract_status",
                "generator_name",
                "generator_version",
                "source_id",
                "normalized_input_id",
                "coverage_status",
                "effective_limits",
                "effective_limits_id",
                "root_preflights",
                "entries",
                "manifest_id",
            },
            label="acquisition manifest",
        )
        if type(data["schema_version"]) is not int:
            raise ValueError("schema_version must be an integer")
        string_fields = {
            "artifact_kind",
            "contract_id",
            "contract_version",
            "contract_status",
            "generator_name",
            "generator_version",
            "source_id",
            "normalized_input_id",
            "coverage_status",
            "effective_limits_id",
            "manifest_id",
        }
        if any(not isinstance(data[field], str) for field in string_fields):
            raise ValueError(
                "acquisition-manifest identity fields are malformed"
            )
        entries = data["entries"]
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
        limits_data = data["effective_limits"]
        if not isinstance(limits_data, dict):
            raise ValueError("effective_limits must be an object")
        try:
            recorded_limits = ReferenceIOLimits(**limits_data)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "acquisition-manifest effective limits are malformed"
            ) from error
        manifest = cls(
            schema_version=cast(int, data["schema_version"]),
            artifact_kind=cast(str, data["artifact_kind"]),
            contract_id=cast(str, data["contract_id"]),
            contract_version=cast(str, data["contract_version"]),
            contract_status=cast(str, data["contract_status"]),
            generator_name=cast(str, data["generator_name"]),
            generator_version=cast(str, data["generator_version"]),
            source_id=cast(str, data["source_id"]),
            normalized_input_id=cast(str, data["normalized_input_id"]),
            coverage_status=cast(str, data["coverage_status"]),
            effective_limits=recorded_limits,
            effective_limits_id=cast(str, data["effective_limits_id"]),
            root_preflights=_parse_root_preflights(data["root_preflights"]),
            entries=tuple(AcquisitionEntry.from_dict(item) for item in entries),
            manifest_id=cast(str, data["manifest_id"]),
        )
        if text != manifest.to_json():
            raise ValueError(
                "acquisition manifest serialization is not canonical"
            )
        return manifest

    @classmethod
    def build(
        cls,
        *,
        source_id: str,
        effective_limits: ReferenceIOLimits,
        root_preflights: tuple[RootPreflightEvidence, ...],
        entries: tuple[AcquisitionEntry, ...],
    ) -> AcquisitionManifest:
        ordered_entries = tuple(sorted(entries, key=_entry_key))
        normalized_input_id = _normalized_input_id(
            source_id=source_id,
            entries=ordered_entries,
        )
        identity_fields: dict[str, object] = {
            "schema_version": ACQUISITION_MANIFEST_SCHEMA_VERSION,
            "artifact_kind": ACQUISITION_ARTIFACT_KIND,
            "contract_id": ACQUISITION_CONTRACT_ID,
            "contract_version": ACQUISITION_CONTRACT_VERSION,
            "contract_status": ACQUISITION_CONTRACT_STATUS,
            "generator_name": ACQUISITION_GENERATOR_NAME,
            "generator_version": ACQUISITION_GENERATOR_VERSION,
            "source_id": source_id,
            "normalized_input_id": normalized_input_id,
            "coverage_status": "complete",
            "effective_limits": effective_limits,
            "effective_limits_id": effective_limits.evidence_id,
            "root_preflights": root_preflights,
            "entries": ordered_entries,
        }
        return cls(
            schema_version=ACQUISITION_MANIFEST_SCHEMA_VERSION,
            artifact_kind=ACQUISITION_ARTIFACT_KIND,
            contract_id=ACQUISITION_CONTRACT_ID,
            contract_version=ACQUISITION_CONTRACT_VERSION,
            contract_status=ACQUISITION_CONTRACT_STATUS,
            generator_name=ACQUISITION_GENERATOR_NAME,
            generator_version=ACQUISITION_GENERATOR_VERSION,
            source_id=source_id,
            normalized_input_id=normalized_input_id,
            coverage_status="complete",
            effective_limits=effective_limits,
            effective_limits_id=effective_limits.evidence_id,
            root_preflights=root_preflights,
            entries=ordered_entries,
            manifest_id=cls.identity_for(**identity_fields),
        )

    @staticmethod
    def identity_for(**values: object) -> str:
        digest = hashlib.sha256(_canonical_json_bytes(values)).hexdigest()
        return f"acquisition-manifest:sha256:{digest}"

    def to_json(self) -> str:
        return (
            json.dumps(
                _manifest_dict(self, include_identity=True),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def projections(self) -> tuple[AcquisitionProjection, ...]:
        return tuple(
            AcquisitionProjection(
                contract_id=self.contract_id,
                contract_version=self.contract_version,
                contract_status=self.contract_status,
                manifest_id=self.manifest_id,
                normalized_input_id=self.normalized_input_id,
                source_id=self.source_id,
                proposed_citekey=entry.proposed_citekey,
                identity_status=entry.identity_status,
                citekey_status=entry.citekey_status,
                manuscript_status=entry.manuscript_status,
                source_content_id=entry.source_content_id,
                source_sha256=entry.sha256,
                source_byte_size=entry.byte_size,
                root_alias=entry.root_alias,
                relative_path=entry.relative_path.as_posix(),
                acquisition=entry.acquisition,
                access=entry.access,
                rights=entry.rights,
                doi=entry.doi,
                source_url=entry.source_url,
                source_version=entry.source_version,
            )
            for entry in self.entries
        )


@dataclass(frozen=True)
class AcquisitionPublicationResult:
    status: str
    manifest_id: str
    output_path: Path

    def __post_init__(self) -> None:
        if self.status not in {"created", "unchanged"}:
            raise ValueError("unsupported acquisition publication status")
        if not _MANIFEST_ID.fullmatch(self.manifest_id):
            raise ValueError("acquisition publication identity is invalid")
        if not isinstance(self.output_path, Path):
            raise ValueError("acquisition output path must be a Path")


def create_acquisition_manifest(
    *,
    source_id: str,
    rows: tuple[dict[str, str], ...],
    roots: tuple[SearchRoot, ...],
    limits: ReferenceIOLimits = ACQUISITION_IO_LIMITS,
) -> AcquisitionManifest:
    max_text_bytes = _required_limit(limits.max_text_bytes, "max_text_bytes")
    _validate_source_id(source_id, max_bytes=max_text_bytes)
    max_rows = _required_limit(limits.max_rows, "max_rows")
    if len(rows) > max_rows:
        raise ReferenceIOLimitError(
            resource="acquisition rows",
            limit_name="max_rows",
            limit=max_rows,
            observed=len(rows),
            limits=limits,
        )
    max_files = _required_limit(limits.max_files, "max_files")
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
        "identity_status",
    }
    allowed = required | {
        "access_status",
        "acquisition_status",
        "asset_status",
        "doi",
        "source_url",
        "source_version",
    }
    for index, row in enumerate(rows, start=2):
        unknown = set(row) - allowed
        if unknown:
            raise ValueError(
                f"CSV row {index} has unknown fields: {sorted(unknown)}"
            )
        missing = tuple(
            field for field in sorted(required) if not row.get(field)
        )
        if missing:
            raise ValueError(
                f"CSV row {index} is missing fields: {list(missing)}"
            )
        access_status = row.get("access_status") or row.get("asset_status")
        if not access_status:
            raise ValueError(
                f"CSV row {index} is missing fields: ['access_status']"
            )
        if (
            row.get("access_status")
            and row.get("asset_status")
            and row["access_status"] != row["asset_status"]
        ):
            raise ValueError(
                f"CSV row {index} has conflicting access and asset status"
            )
        proposed_citekey = validate_citekey(
            _bounded(
                row["proposed_citekey"],
                field="proposed_citekey",
                max_bytes=max_text_bytes,
            ),
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
        relative_path = _relative_path(
            _bounded(
                row["relative_path"],
                field="relative_path",
                max_bytes=max_text_bytes,
            )
        )
        rights_status = _bounded(
            row["rights_status"],
            field="rights_status",
            max_bytes=max_text_bytes,
        )
        access_status = _bounded(
            access_status,
            field="access_status",
            max_bytes=max_text_bytes,
        )
        acquisition_status = row.get("acquisition_status") or "not-assessed"
        acquisition_status = _bounded(
            acquisition_status,
            field="acquisition_status",
            max_bytes=max_text_bytes,
        )
        identity_status = _bounded(
            row["identity_status"],
            field="identity_status",
            max_bytes=max_text_bytes,
        )
        if identity_status != _IDENTITY_STATUS:
            raise ValueError("unsupported identity_status")
        raw_doi = row.get("doi") or None
        if raw_doi is not None:
            _bounded(raw_doi, field="doi", max_bytes=max_text_bytes)
        doi = normalize_doi(raw_doi)
        source_url = row.get("source_url") or None
        source_version = row.get("source_version") or None
        if source_url is not None:
            _validate_source_url(source_url, max_bytes=max_text_bytes)
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
        if len(observed_sources) >= max_files:
            raise ReferenceIOLimitError(
                resource="acquisition source files",
                limit_name="max_files",
                limit=max_files,
                observed=len(observed_sources) + 1,
                limits=limits,
            )
        observed_sources.add(source_identity)
        observation = _observe_source(
            root_alias,
            relative_path,
            root_paths,
            aggregate_bytes_observed=total_bytes,
            limits=limits,
        )
        if observation.byte_size <= 0:
            raise ValueError(f"CSV row {index} source is empty")
        if observation.prefix != b"%PDF-":
            raise ValueError(f"CSV row {index} source has no PDF header")
        entries.append(
            AcquisitionEntry(
                proposed_citekey=proposed_citekey,
                identity_status=identity_status,
                citekey_status=_CITEKEY_STATUS,
                manuscript_status=_MANUSCRIPT_STATUS,
                root_alias=root_alias,
                relative_path=relative_path,
                sha256=observation.sha256,
                byte_size=observation.byte_size,
                acquisition=AcquisitionObservation(
                    status=acquisition_status,
                    basis=(
                        "explicitly-not-assessed"
                        if "acquisition_status" not in row
                        or not row["acquisition_status"]
                        else "operator-assertion"
                    ),
                ),
                access=AccessObservation(
                    status=access_status,
                    basis="operator-assertion",
                ),
                rights=RightsObservation(
                    status=rights_status,
                    basis="operator-assertion",
                ),
                doi=doi,
                source_url=source_url,
                source_version=source_version,
            )
        )
        total_bytes += observation.byte_size
    manifest = AcquisitionManifest.build(
        source_id=source_id,
        effective_limits=limits,
        root_preflights=tuple(
            sorted(
                (root_paths[root.alias].preflight_evidence for root in roots),
                key=lambda item: item.root_alias,
            )
        ),
        entries=tuple(entries),
    )
    manifest_size = len(manifest.to_json().encode("utf-8"))
    max_json_bytes = _required_limit(limits.max_json_bytes, "max_json_bytes")
    if manifest_size > max_json_bytes:
        raise ReferenceIOLimitError(
            resource="acquisition manifest JSON",
            limit_name="max_json_bytes",
            limit=max_json_bytes,
            observed=manifest_size,
            limits=limits,
        )
    return manifest


def verify_acquisition_manifest(
    manifest: AcquisitionManifest,
    *,
    roots: tuple[SearchRoot, ...],
    limits: ReferenceIOLimits | None = None,
) -> None:
    effective_limits = manifest.effective_limits if limits is None else limits
    if effective_limits != manifest.effective_limits:
        raise ValueError(
            "verification limits differ from the manifest effective limits"
        )
    max_rows = _required_limit(effective_limits.max_rows, "max_rows")
    if len(manifest.entries) > max_rows:
        raise ReferenceIOLimitError(
            resource="acquisition manifest entries",
            limit_name="max_rows",
            limit=max_rows,
            observed=len(manifest.entries),
            limits=effective_limits,
        )
    max_files = _required_limit(effective_limits.max_files, "max_files")
    if len(manifest.entries) > max_files:
        raise ReferenceIOLimitError(
            resource="acquisition source files",
            limit_name="max_files",
            limit=max_files,
            observed=len(manifest.entries),
            limits=effective_limits,
        )
    root_paths = _resolved_roots(roots, limits=effective_limits)
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
            aggregate_bytes_observed=total_bytes,
            limits=effective_limits,
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


def publish_acquisition_manifest(
    manifest: AcquisitionManifest,
    *,
    output_path: Path,
    output_storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
) -> AcquisitionPublicationResult:
    """Atomically create a manifest, or accept an exact byte replay only."""
    content = manifest.to_json().encode("utf-8")
    maximum = _required_limit(
        manifest.effective_limits.max_json_bytes, "max_json_bytes"
    )
    if len(content) > maximum:
        raise ReferenceIOLimitError(
            resource="acquisition manifest JSON",
            limit_name="max_json_bytes",
            limit=maximum,
            observed=len(content),
            limits=manifest.effective_limits,
        )
    root = AuthorizedRoot.create(
        output_path.expanduser().parent,
        label="acquisition manifest output parent",
        root_alias="acquisition-manifest-output",
        storage_class=output_storage_class,
        placeholder_probe=placeholder_probe,
    )
    filename = output_path.name
    state = root.state(filename)
    if state == "regular":
        _require_identical_existing(
            root,
            filename,
            content,
            maximum=maximum,
            limits=manifest.effective_limits,
        )
        return AcquisitionPublicationResult(
            "unchanged", manifest.manifest_id, root.child_path(filename)
        )
    if state != "missing":
        raise AcquisitionPublicationError(
            "acquisition manifest output is not a regular file"
        )
    try:
        published = root.write_bytes(filename, content, replace=False)
    except FileExistsError:
        _require_identical_existing(
            root,
            filename,
            content,
            maximum=maximum,
            limits=manifest.effective_limits,
        )
        return AcquisitionPublicationResult(
            "unchanged", manifest.manifest_id, root.child_path(filename)
        )
    return AcquisitionPublicationResult(
        "created", manifest.manifest_id, published
    )


def _require_identical_existing(
    root: AuthorizedRoot,
    filename: str,
    expected: bytes,
    *,
    maximum: int,
    limits: ReferenceIOLimits,
) -> None:
    try:
        actual = root.read_bytes(filename, max_bytes=maximum)
    except PathLimitError as error:
        raise ReferenceIOLimitError(
            resource=error.resource,
            limit_name=error.limit_name,
            limit=error.limit,
            observed=error.observed,
            limits=limits,
        ) from error
    if actual != expected:
        raise AcquisitionPublicationError(
            "existing acquisition manifest differs; refusing partial repair"
        )


def _resolved_roots(
    roots: tuple[SearchRoot, ...],
    *,
    limits: ReferenceIOLimits,
) -> dict[str, AuthorizedRoot]:
    if not roots:
        raise ValueError("at least one source root is required")
    max_entries = _required_limit(limits.max_entries, "max_entries")
    if len(roots) > max_entries:
        raise ReferenceIOLimitError(
            resource="acquisition source roots",
            limit_name="max_entries",
            limit=max_entries,
            observed=len(roots),
            limits=limits,
        )
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("source-root aliases must be unique")
    return {
        root.alias: AuthorizedRoot.existing(
            root.path,
            label=f"source root {root.alias!r}",
            root_alias=root.alias,
            storage_class=root.storage_class,
            placeholder_probe=root.placeholder_probe,
        )
        for root in roots
    }


def _observe_source(
    root_alias: str,
    relative_path: PurePosixPath,
    roots: dict[str, AuthorizedRoot],
    *,
    aggregate_bytes_observed: int,
    limits: ReferenceIOLimits,
) -> FileObservation:
    if root_alias not in roots:
        raise ValueError(f"source root was not supplied: {root_alias}")
    max_file_bytes = _required_limit(limits.max_file_bytes, "max_file_bytes")
    max_total_bytes = _required_limit(limits.max_total_bytes, "max_total_bytes")
    remaining_total = max_total_bytes - aggregate_bytes_observed
    if remaining_total <= 0:
        raise ReferenceIOLimitError(
            resource="acquisition sources",
            limit_name="max_total_bytes",
            limit=max_total_bytes,
            observed=aggregate_bytes_observed + 1,
            limits=limits,
        )
    observation_limit = min(max_file_bytes, remaining_total)
    try:
        roots[root_alias].require_readable_file(relative_path)
        return roots[root_alias].observe_file(
            relative_path,
            max_bytes=observation_limit,
            prefix_bytes=5,
        )
    except FileNotFoundError as error:
        raise ValueError(
            f"source is not a regular file: {relative_path}"
        ) from error
    except PathLimitError as error:
        aggregate_limited = remaining_total < max_file_bytes
        raise ReferenceIOLimitError(
            resource=(
                "acquisition sources" if aggregate_limited else error.resource
            ),
            limit_name=(
                "max_total_bytes" if aggregate_limited else error.limit_name
            ),
            limit=(max_total_bytes if aggregate_limited else error.limit),
            observed=(
                aggregate_bytes_observed + error.observed
                if aggregate_limited
                else error.observed
            ),
            limits=limits,
        ) from error


def _normalized_input_id(
    *,
    source_id: str,
    entries: tuple[AcquisitionEntry, ...],
) -> str:
    payload = {
        "contract_id": ACQUISITION_CONTRACT_ID,
        "contract_version": ACQUISITION_CONTRACT_VERSION,
        "generator_name": ACQUISITION_GENERATOR_NAME,
        "generator_version": ACQUISITION_GENERATOR_VERSION,
        "rows": [entry.normalized_input_dict() for entry in entries],
        "source_id": source_id,
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return f"acquisition-input:sha256:{digest}"


def _manifest_dict(
    manifest: AcquisitionManifest,
    *,
    include_identity: bool,
) -> dict[str, object]:
    value: dict[str, object] = {
        "artifact_kind": manifest.artifact_kind,
        "contract_id": manifest.contract_id,
        "contract_status": manifest.contract_status,
        "contract_version": manifest.contract_version,
        "coverage_status": manifest.coverage_status,
        "effective_limits": manifest.effective_limits.to_dict(),
        "effective_limits_id": manifest.effective_limits_id,
        "entries": [entry.to_dict() for entry in manifest.entries],
        "generator_name": manifest.generator_name,
        "generator_version": manifest.generator_version,
        "normalized_input_id": manifest.normalized_input_id,
        "root_preflights": [
            {
                "probe_id": item.probe_id,
                "probe_support": (
                    None
                    if item.probe_support is None
                    else item.probe_support.value
                ),
                "root_alias": item.root_alias,
                "storage_class": item.storage_class.value,
            }
            for item in manifest.root_preflights
        ],
        "schema_version": manifest.schema_version,
        "source_id": manifest.source_id,
    }
    if include_identity:
        value["manifest_id"] = manifest.manifest_id
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _jsonable(value: object) -> object:
    if isinstance(value, ReferenceIOLimits):
        return value.to_dict()
    if isinstance(value, AcquisitionEntry):
        return value.to_dict()
    if isinstance(value, RootPreflightEvidence):
        return {
            "probe_id": value.probe_id,
            "probe_support": (
                None
                if value.probe_support is None
                else value.probe_support.value
            ),
            "root_alias": value.root_alias,
            "storage_class": value.storage_class.value,
        }
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _entry_key(entry: AcquisitionEntry) -> tuple[str, str, str]:
    return (
        entry.proposed_citekey,
        entry.root_alias,
        entry.relative_path.as_posix(),
    )


def _relative_path(value: str) -> PurePosixPath:
    return validate_relative_path(value)


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


def _validate_source_id(
    value: object,
    *,
    max_bytes: int = _MAX_TEXT,
) -> str:
    source_id = _bounded(value, field="source_id", max_bytes=max_bytes)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", source_id) is None:
        raise ValueError("source_id must be a path-free portable identifier")
    return source_id


def _validate_source_url(value: str, *, max_bytes: int = _MAX_TEXT) -> None:
    _bounded(value, field="source_url", max_bytes=max_bytes)
    message = (
        "source_url must be an HTTP(S) URL without credentials, query, "
        "or fragment"
    )
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        raise ValueError(message) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError(message)


def _validate_observation_basis(value: object) -> str:
    if not isinstance(value, str) or value not in _OBSERVATION_BASES:
        raise ValueError("observation basis is unsupported")
    return value


def _parse_observation(value: object, label: str) -> tuple[str, str]:
    data = _exact_object(value, fields={"status", "basis"}, label=label)
    if not isinstance(data["status"], str) or not isinstance(
        data["basis"], str
    ):
        raise ValueError(f"{label} fields must be strings")
    return cast(str, data["status"]), cast(str, data["basis"])


def _parse_root_preflights(value: object) -> tuple[RootPreflightEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("root_preflights must be an array")
    expected = {"root_alias", "storage_class", "probe_id", "probe_support"}
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
                limits.max_text_bytes, "max_text_bytes"
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


def _exact_object(
    value: object,
    *,
    fields: set[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing or unknown:
        raise ValueError(
            f"{label} fields differ: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    return value
