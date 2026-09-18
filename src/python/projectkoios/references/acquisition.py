from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from projectkoios.references.assets import SearchRoot
from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ENTRIES = 256
_MAX_TEXT = 4096
_IDENTITY_STATUSES = frozenset({"accepted-reference", "unaccepted-candidate"})


def _bounded(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
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
    entries: tuple[AcquisitionEntry, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported acquisition-manifest schema version")
        _bounded(self.source_id, field="source_id")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("acquisition manifest must contain an entry tuple")
        if any(
            not isinstance(entry, AcquisitionEntry) for entry in self.entries
        ):
            raise ValueError("manifest entries must be AcquisitionEntry values")
        if len(self.entries) > _MAX_ENTRIES:
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

    @classmethod
    def from_json(cls, text: str) -> AcquisitionManifest:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("acquisition manifest must be an object")
        unknown = set(data) - {"schema_version", "source_id", "entries"}
        if unknown:
            raise ValueError(
                f"unknown acquisition-manifest fields: {sorted(unknown)}"
            )
        if type(data.get("schema_version")) is not int:
            raise ValueError("schema_version must be an integer")
        if not isinstance(data.get("source_id"), str):
            raise ValueError("source_id must be a string")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("entries must be an array")
        return cls(
            schema_version=data["schema_version"],
            source_id=data["source_id"],
            entries=tuple(AcquisitionEntry.from_dict(item) for item in entries),
        )

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "source_id": self.source_id,
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
) -> AcquisitionManifest:
    root_paths = _resolved_roots(roots)
    entries: list[AcquisitionEntry] = []
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
        root_alias = row["root_alias"]
        relative_path = _relative_path(row["relative_path"])
        content = _read_source(root_alias, relative_path, root_paths)
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"CSV row {index} source has no PDF header")
        entries.append(
            AcquisitionEntry(
                proposed_citekey=row["proposed_citekey"],
                root_alias=root_alias,
                relative_path=relative_path,
                sha256=hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
                rights_status=row["rights_status"],
                asset_status=row["asset_status"],
                identity_status=row["identity_status"],
                doi=normalize_doi(row.get("doi") or None),
                source_url=row.get("source_url") or None,
                source_version=row.get("source_version") or None,
            )
        )
    return AcquisitionManifest(1, source_id, tuple(entries))


def verify_acquisition_manifest(
    manifest: AcquisitionManifest,
    *,
    roots: tuple[SearchRoot, ...],
) -> None:
    root_paths = _resolved_roots(roots)
    for entry in manifest.entries:
        content = _read_source(
            entry.root_alias, entry.relative_path, root_paths
        )
        if not content.startswith(b"%PDF-"):
            raise ValueError(
                f"source has no PDF header: {entry.proposed_citekey}"
            )
        if len(content) != entry.byte_size:
            raise ValueError(f"source size changed: {entry.proposed_citekey}")
        if hashlib.sha256(content).hexdigest() != entry.sha256:
            raise ValueError(f"source hash changed: {entry.proposed_citekey}")


def _resolved_roots(
    roots: tuple[SearchRoot, ...],
) -> dict[str, AuthorizedRoot]:
    if not roots:
        raise ValueError("at least one source root is required")
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("source-root aliases must be unique")
    resolved: dict[str, AuthorizedRoot] = {}
    for root in roots:
        resolved[root.alias] = AuthorizedRoot.existing(
            root.path,
            label=f"source root {root.alias!r}",
        )
    return resolved


def _read_source(
    root_alias: str,
    relative_path: PurePosixPath,
    roots: dict[str, AuthorizedRoot],
) -> bytes:
    if root_alias not in roots:
        raise ValueError(f"source root was not supplied: {root_alias}")
    try:
        return roots[root_alias].read_bytes(relative_path)
    except FileNotFoundError as error:
        raise ValueError(
            f"source is not a regular file: {relative_path}"
        ) from error
