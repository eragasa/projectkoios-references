from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Self, cast

from projectkoios.references.io_limits import (
    RECONCILIATION_PACKAGE_IO_LIMITS,
    ReferenceIOLimitError,
    bounded_utf8_size,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    PathLimitError,
    PathSafetyError,
    validate_relative_path,
)

PACKAGE_MANIFEST_FILENAME = "package-manifest.json"
PACKAGE_FORMAT_VERSION = 1
PACKAGE_ARTIFACT_KIND = "projectkoios.references.reconciliation-package"
PACKAGE_DISTRIBUTION = "projectkoios-references"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_PACKAGE_FILES = 100_000
_MAX_PACKAGE_FILE_BYTES = 50_000_000
_MAX_PACKAGE_TOTAL_BYTES = 100_000_000
_MAX_PACKAGE_MANIFEST_BYTES = 20_000_000
_MAX_JSON_DEPTH = 64


class ReconciliationPackageError(RuntimeError):
    """Raised when a reconciliation package is malformed or differs."""


class ReconciliationPackageLimitError(
    ReferenceIOLimitError,
    ReconciliationPackageError,
):
    """Raised when package verification reaches a declared I/O bound."""


@dataclass(frozen=True, slots=True, init=False, eq=False)
class FrozenCounts(Mapping[str, int]):
    """Small immutable mapping used by content-identified records."""

    _items: tuple[tuple[str, int], ...]

    def __init__(self, values: Mapping[str, int] | Iterable[tuple[str, int]]):
        items = tuple(sorted(dict(values).items()))
        if any(
            not isinstance(key, str)
            or not key
            or type(value) is not int
            or value < 0
            for key, value in items
        ):
            raise ValueError("counts must contain non-negative integer values")
        object.__setattr__(self, "_items", items)

    def __getitem__(self, key: str) -> int:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"FrozenCounts({dict(self._items)!r})"

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        del memo
        return self


@dataclass(frozen=True)
class ContentEvidence:
    """Content identity for one package input or payload output."""

    role: str
    filename: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not self.role:
            raise ValueError("content-evidence role must be non-empty")
        try:
            normalized = validate_relative_path(
                self.filename,
                field="content-evidence filename",
            ).as_posix()
        except PathSafetyError as error:
            raise ValueError(str(error)) from error
        if normalized != self.filename:
            raise ValueError("content-evidence filename must be normalized")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("content-evidence byte_size must be non-negative")
        if (
            not isinstance(self.sha256, str)
            or _SHA256.fullmatch(self.sha256) is None
        ):
            raise ValueError("content-evidence SHA-256 must be lowercase hex")

    @classmethod
    def from_bytes(cls, *, role: str, filename: str, content: bytes) -> Self:
        return cls(
            role=role,
            filename=filename,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={"role", "filename", "byte_size", "sha256"},
            label="content evidence",
        )
        if (
            not isinstance(data["role"], str)
            or not isinstance(data["filename"], str)
            or type(data["byte_size"]) is not int
            or not isinstance(data["sha256"], str)
        ):
            raise ValueError("content-evidence fields have invalid types")
        return cls(
            role=cast(str, data["role"]),
            filename=cast(str, data["filename"]),
            byte_size=cast(int, data["byte_size"]),
            sha256=cast(str, data["sha256"]),
        )


@dataclass(frozen=True)
class SoftwareIdentity:
    name: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("software name must be non-empty")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("software version must be non-empty")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={"name", "version"},
            label="software identity",
        )
        if not isinstance(data["name"], str) or not isinstance(
            data["version"], str
        ):
            raise ValueError("software identity fields must be strings")
        return cls(
            name=cast(str, data["name"]),
            version=cast(str, data["version"]),
        )


@dataclass(frozen=True)
class VerifiedSourceTree:
    """Git identity verified locally against a clean exact HEAD."""

    commit_id: str
    tree_id: str
    verification_method: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.commit_id):
            raise ValueError("verified source commit must be a full object ID")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.tree_id):
            raise ValueError("verified source tree must be a full object ID")
        if self.verification_method != "git-clean-head":
            raise ValueError("unsupported source-tree verification method")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={"commit_id", "tree_id", "verification_method"},
            label="verified source tree",
        )
        if not all(isinstance(data[field], str) for field in data):
            raise ValueError("verified source-tree fields must be strings")
        return cls(
            commit_id=cast(str, data["commit_id"]),
            tree_id=cast(str, data["tree_id"]),
            verification_method=cast(str, data["verification_method"]),
        )


@dataclass(frozen=True)
class ReconciliationPackageManifest:
    schema_version: int
    artifact_kind: str
    collection_id: str
    asserted_source_revision: str
    verified_source_tree: VerifiedSourceTree | None
    generator: SoftwareIdentity
    components: tuple[SoftwareIdentity, ...]
    inputs: tuple[ContentEvidence, ...]
    outputs: tuple[ContentEvidence, ...]
    package_id: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != PACKAGE_FORMAT_VERSION
        ):
            raise ValueError(
                "unsupported reconciliation-package schema version"
            )
        if self.artifact_kind != PACKAGE_ARTIFACT_KIND:
            raise ValueError("unsupported reconciliation-package artifact kind")
        if (
            not isinstance(self.collection_id, str)
            or not self.collection_id
            or not isinstance(self.asserted_source_revision, str)
            or not self.asserted_source_revision
        ):
            raise ValueError(
                "package collection and assertion must be non-empty strings"
            )
        if self.verified_source_tree is not None and not isinstance(
            self.verified_source_tree, VerifiedSourceTree
        ):
            raise ValueError("package verified source-tree evidence is invalid")
        if not isinstance(self.generator, SoftwareIdentity):
            raise ValueError("package generator identity is invalid")
        if not isinstance(self.components, tuple) or any(
            not isinstance(item, SoftwareIdentity) for item in self.components
        ):
            raise ValueError(
                "package components must be a software-identity tuple"
            )
        _validate_sorted_unique(
            self.components,
            key=lambda item: (item.name, item.version),
            label="package components",
        )
        _validate_evidence(self.inputs, label="package inputs")
        _validate_evidence(self.outputs, label="package outputs")
        if any(
            item.filename == PACKAGE_MANIFEST_FILENAME for item in self.outputs
        ):
            raise ValueError("package manifest cannot recursively list itself")
        expected = self.identity_for(
            schema_version=self.schema_version,
            artifact_kind=self.artifact_kind,
            collection_id=self.collection_id,
            asserted_source_revision=self.asserted_source_revision,
            verified_source_tree=self.verified_source_tree,
            generator=self.generator,
            components=self.components,
            inputs=self.inputs,
            outputs=self.outputs,
        )
        if self.package_id != expected:
            raise ValueError("reconciliation package identity does not match")

    @classmethod
    def create(
        cls,
        *,
        collection_id: str,
        asserted_source_revision: str,
        verified_source_tree: VerifiedSourceTree | None,
        components: tuple[SoftwareIdentity, ...],
        inputs: tuple[ContentEvidence, ...],
        output_files: Mapping[str, bytes],
    ) -> Self:
        outputs = tuple(
            sorted(
                (
                    ContentEvidence.from_bytes(
                        role="package-output",
                        filename=name,
                        content=content,
                    )
                    for name, content in output_files.items()
                ),
                key=_evidence_key,
            )
        )
        generator = SoftwareIdentity(
            name=PACKAGE_DISTRIBUTION,
            version=package_version(),
        )
        ordered_components = tuple(
            sorted(components, key=lambda item: (item.name, item.version))
        )
        ordered_inputs = tuple(sorted(inputs, key=_evidence_key))
        fields_without_identity = {
            "schema_version": PACKAGE_FORMAT_VERSION,
            "artifact_kind": PACKAGE_ARTIFACT_KIND,
            "collection_id": collection_id,
            "asserted_source_revision": asserted_source_revision,
            "verified_source_tree": verified_source_tree,
            "generator": generator,
            "components": ordered_components,
            "inputs": ordered_inputs,
            "outputs": outputs,
        }
        return cls(
            schema_version=PACKAGE_FORMAT_VERSION,
            artifact_kind=PACKAGE_ARTIFACT_KIND,
            collection_id=collection_id,
            asserted_source_revision=asserted_source_revision,
            verified_source_tree=verified_source_tree,
            generator=generator,
            components=ordered_components,
            inputs=ordered_inputs,
            outputs=outputs,
            package_id=cls.identity_for(**fields_without_identity),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        if (
            bounded_utf8_size(
                text,
                max_bytes=_MAX_PACKAGE_MANIFEST_BYTES,
            )
            > _MAX_PACKAGE_MANIFEST_BYTES
        ):
            raise _limit_error(
                resource="reconciliation package manifest",
                limit_name="max_json_bytes",
                limit=_MAX_PACKAGE_MANIFEST_BYTES,
                observed=_MAX_PACKAGE_MANIFEST_BYTES + 1,
            )
        _validate_json_nesting(text)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("package manifest is not valid JSON") from error
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "artifact_kind",
                "collection_id",
                "asserted_source_revision",
                "verified_source_tree",
                "generator",
                "components",
                "inputs",
                "outputs",
                "package_id",
            },
            label="reconciliation package manifest",
        )
        if type(data["schema_version"]) is not int:
            raise ValueError("package schema_version must be an integer")
        for field in (
            "artifact_kind",
            "collection_id",
            "asserted_source_revision",
            "package_id",
        ):
            if not isinstance(data[field], str):
                raise ValueError(f"package {field} must be a string")
        if not isinstance(data["components"], list):
            raise ValueError("package components must be an array")
        if len(data["components"]) > _MAX_PACKAGE_FILES:
            raise _limit_error(
                resource="reconciliation package components",
                limit_name="max_files",
                limit=_MAX_PACKAGE_FILES,
                observed=len(data["components"]),
            )
        if not isinstance(data["inputs"], list) or not isinstance(
            data["outputs"], list
        ):
            raise ValueError("package inputs and outputs must be arrays")
        if (
            len(data["inputs"]) > _MAX_PACKAGE_FILES
            or len(data["outputs"]) > _MAX_PACKAGE_FILES
        ):
            raise _limit_error(
                resource="reconciliation package evidence",
                limit_name="max_entries",
                limit=_MAX_PACKAGE_FILES,
                observed=max(len(data["inputs"]), len(data["outputs"])),
            )
        source = data["verified_source_tree"]
        manifest = cls(
            schema_version=cast(int, data["schema_version"]),
            artifact_kind=cast(str, data["artifact_kind"]),
            collection_id=cast(str, data["collection_id"]),
            asserted_source_revision=cast(
                str, data["asserted_source_revision"]
            ),
            verified_source_tree=(
                None if source is None else VerifiedSourceTree.from_dict(source)
            ),
            generator=SoftwareIdentity.from_dict(data["generator"]),
            components=tuple(
                SoftwareIdentity.from_dict(item)
                for item in cast(list[object], data["components"])
            ),
            inputs=tuple(
                ContentEvidence.from_dict(item)
                for item in cast(list[object], data["inputs"])
            ),
            outputs=tuple(
                ContentEvidence.from_dict(item)
                for item in cast(list[object], data["outputs"])
            ),
            package_id=cast(str, data["package_id"]),
        )
        if text != manifest.to_json():
            raise ValueError("package manifest serialization is not canonical")
        return manifest

    def to_json(self) -> str:
        return pretty_json(self)

    @staticmethod
    def identity_for(**values: object) -> str:
        digest = hashlib.sha256(canonical_json_bytes(values)).hexdigest()
        return f"reconciliation-package:sha256:{digest}"


@dataclass(frozen=True)
class LoadedReconciliationPackage:
    manifest: ReconciliationPackageManifest
    files: tuple[tuple[str, bytes], ...]


def package_version() -> str:
    """Return the installed distribution version from the build metadata."""
    try:
        return version(PACKAGE_DISTRIBUTION)
    except PackageNotFoundError as error:
        raise ReconciliationPackageError(
            "package distribution metadata is unavailable"
        ) from error


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def pretty_json(value: object) -> str:
    return (
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def verify_package_files(
    manifest: ReconciliationPackageManifest,
    files: Mapping[str, bytes],
) -> None:
    expected_names = {item.filename for item in manifest.outputs}
    if set(files) != expected_names:
        raise ReconciliationPackageError(
            "reconciliation package payload is incomplete or unexpected"
        )
    for evidence in manifest.outputs:
        content = files[evidence.filename]
        actual = ContentEvidence.from_bytes(
            role=evidence.role,
            filename=evidence.filename,
            content=content,
        )
        if actual != evidence:
            raise ReconciliationPackageError(
                f"reconciliation package output differs: {evidence.filename}"
            )


def parse_package_files(
    files: Mapping[str, bytes],
) -> LoadedReconciliationPackage:
    if len(files) > _MAX_PACKAGE_FILES:
        raise _limit_error(
            resource="reconciliation package files",
            limit_name="max_files",
            limit=_MAX_PACKAGE_FILES,
            observed=len(files),
        )
    oversized = [
        name
        for name, content in files.items()
        if len(content) > _MAX_PACKAGE_FILE_BYTES
    ]
    if oversized:
        raise _limit_error(
            resource=("reconciliation package file " + sorted(oversized)[0]),
            limit_name="max_file_bytes",
            limit=_MAX_PACKAGE_FILE_BYTES,
            observed=max(len(files[name]) for name in oversized),
        )
    total_bytes = sum(len(content) for content in files.values())
    if total_bytes > _MAX_PACKAGE_TOTAL_BYTES:
        raise _limit_error(
            resource="reconciliation package",
            limit_name="max_total_bytes",
            limit=_MAX_PACKAGE_TOTAL_BYTES,
            observed=total_bytes,
        )
    manifest_bytes = files.get(PACKAGE_MANIFEST_FILENAME)
    if manifest_bytes is None:
        raise ReconciliationPackageError(
            "reconciliation package manifest is missing"
        )
    if len(manifest_bytes) > _MAX_PACKAGE_MANIFEST_BYTES:
        raise _limit_error(
            resource="reconciliation package manifest",
            limit_name="max_json_bytes",
            limit=_MAX_PACKAGE_MANIFEST_BYTES,
            observed=len(manifest_bytes),
        )
    try:
        manifest = ReconciliationPackageManifest.from_json(
            manifest_bytes.decode("utf-8")
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise ReconciliationPackageError(str(error)) from error
    payload = {
        name: content
        for name, content in files.items()
        if name != PACKAGE_MANIFEST_FILENAME
    }
    verify_package_files(manifest, payload)
    return LoadedReconciliationPackage(
        manifest=manifest,
        files=tuple(sorted(files.items())),
    )


def load_reconciliation_package(
    directory: Path,
) -> LoadedReconciliationPackage:
    try:
        root = AuthorizedRoot.existing(
            directory,
            label="reconciliation package directory",
        )
        relative_files = root.iter_files(
            suffix="",
            recursive=False,
            reject_directories=True,
            max_files=_MAX_PACKAGE_FILES,
            max_entries=_MAX_PACKAGE_FILES,
            max_depth=1,
        )
        files: dict[str, bytes] = {}
        total_bytes = 0
        for item in relative_files:
            content = root.read_bytes(
                item,
                max_bytes=_MAX_PACKAGE_FILE_BYTES,
            )
            total_bytes += len(content)
            if total_bytes > _MAX_PACKAGE_TOTAL_BYTES:
                raise _limit_error(
                    resource="reconciliation package",
                    limit_name="max_total_bytes",
                    limit=_MAX_PACKAGE_TOTAL_BYTES,
                    observed=total_bytes,
                )
            files[item.name] = content
    except PathLimitError as error:
        raise _limit_error(
            resource=error.resource,
            limit_name=error.limit_name,
            limit=error.limit,
            observed=error.observed,
        ) from error
    except PathSafetyError as error:
        raise ReconciliationPackageError(str(error)) from error
    return parse_package_files(files)


def _validate_json_nesting(text: str) -> None:
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if character in "[{":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise _limit_error(
                    resource="reconciliation package manifest",
                    limit_name="max_json_depth",
                    limit=_MAX_JSON_DEPTH,
                    observed=depth,
                )
        elif character in "]}":
            depth = max(0, depth - 1)


def _jsonable(value: object) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, FrozenCounts):
        return dict(value.items())
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _validate_evidence(
    values: tuple[ContentEvidence, ...],
    *,
    label: str,
) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, ContentEvidence) for item in values
    ):
        raise ValueError(f"{label} must be a content-evidence tuple")
    if len(values) > _MAX_PACKAGE_FILES:
        raise _limit_error(
            resource=label,
            limit_name="max_entries",
            limit=_MAX_PACKAGE_FILES,
            observed=len(values),
        )
    _validate_sorted_unique(values, key=_evidence_key, label=label)
    names = tuple(item.filename for item in values)
    if len(names) != len(set(names)):
        raise ValueError(f"{label} contains duplicate filenames")


def _validate_sorted_unique(
    values: Sequence[Any],
    *,
    key: Any,
    label: str,
) -> None:
    keys = tuple(key(item) for item in values)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError(f"{label} must be sorted and unique")


def _evidence_key(value: ContentEvidence) -> tuple[str, str, int, str]:
    return (value.role, value.filename, value.byte_size, value.sha256)


def _limit_error(
    *,
    resource: str,
    limit_name: str,
    limit: int,
    observed: int,
) -> ReconciliationPackageLimitError:
    return ReconciliationPackageLimitError(
        resource=resource,
        limit_name=limit_name,
        limit=limit,
        observed=observed,
        limits=RECONCILIATION_PACKAGE_IO_LIMITS,
    )


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
