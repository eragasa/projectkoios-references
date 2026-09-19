from __future__ import annotations

import errno
import hashlib
import os
import re
import secrets
import stat
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal, Never, Protocol

_CITEKEY_MAX_LENGTH = 200
_DEFAULT_READ_MAX_BYTES = 50_000_000
_MAX_STREAMED_FILE_BYTES = 4_000_000_000
_MAX_DIRECTORY_ENTRIES = 100_000
_MAX_DIRECTORY_DEPTH = 128
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_CITEKEY_ASCII = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_PORTABLE_FORBIDDEN = frozenset('<>:"\\|?*')
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)


class PathSafetyError(ValueError):
    """Raised when a path cannot be used within an authorized root."""


class CloudRootMutationError(PathSafetyError):
    """Raised before attempting mutation of a cloud-backed root."""

    code = "cloud-root-mutation-forbidden"


class PlaceholderPreflightError(PathSafetyError):
    """Raised when cloud-placeholder safety cannot permit byte access."""

    code = "placeholder-preflight-incomplete"
    coverage_status = "incomplete"

    def __init__(self, observation: PlaceholderObservation) -> None:
        self.observation = observation
        super().__init__(
            "cloud-placeholder preflight refused access: "
            f"{observation.root_alias}/{observation.relative_path or '<root>'} "
            f"is {observation.status.value}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "coverage_status": self.coverage_status,
            "root_alias": self.observation.root_alias,
            "relative_path": self.observation.relative_path,
            "storage_class": self.observation.storage_class.value,
            "probe_id": self.observation.probe_id,
            "status": self.observation.status.value,
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


class PathLimitError(PathSafetyError):
    """Raised before a bounded filesystem observation can become partial."""

    coverage_status = "incomplete"

    def __init__(
        self,
        *,
        resource: str,
        limit_name: str,
        limit: int,
        observed: int,
    ) -> None:
        self.resource = resource
        self.limit_name = limit_name
        self.limit = limit
        self.observed = observed
        super().__init__(
            f"{resource} exceeds {limit_name}: observed {observed}, "
            f"limit {limit}; coverage remains incomplete"
        )


class RootStorageClass(StrEnum):
    """Operator-declared storage semantics for an authorized root."""

    LOCAL = "local"
    CLOUD_BACKED = "cloud-backed"


class PlaceholderProbeSupport(StrEnum):
    """Whether a probe can safely classify this cloud-backed root."""

    SUPPORTED = "supported"
    UNSUPPORTED_PLATFORM = "unsupported-platform"


class PlaceholderStatus(StrEnum):
    """A metadata-only classification made before candidate byte access."""

    ORDINARY_FILE = "ordinary-file"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    MISSING = "missing"
    ACCESS_CONTROLLED = "access-controlled"
    UNREADABLE = "unreadable"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RootPreflightEvidence:
    """Privacy-reduced evidence for one declared root capability."""

    root_alias: str
    storage_class: RootStorageClass
    probe_id: str
    probe_support: PlaceholderProbeSupport | None

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        _validate_probe_id(self.probe_id)
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("root storage class must be explicit")
        if self.probe_support is not None and not isinstance(
            self.probe_support, PlaceholderProbeSupport
        ):
            raise ValueError("placeholder probe support is invalid")
        if self.storage_class is RootStorageClass.LOCAL:
            if self.probe_support is not None:
                raise ValueError("local roots cannot claim cloud-probe support")
        elif self.probe_support is None:
            raise ValueError(
                "cloud-backed roots require probe support evidence"
            )


@dataclass(frozen=True)
class PlaceholderObservation:
    """A privacy-reduced, metadata-only candidate-path observation."""

    root_alias: str
    relative_path: str | None
    storage_class: RootStorageClass
    probe_id: str
    status: PlaceholderStatus

    def __post_init__(self) -> None:
        validate_root_alias(self.root_alias)
        _validate_probe_id(self.probe_id)
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("root storage class must be explicit")
        if not isinstance(self.status, PlaceholderStatus):
            raise ValueError("placeholder status is invalid")
        if self.relative_path is not None:
            validate_relative_path(self.relative_path)
        if self.storage_class is RootStorageClass.LOCAL and self.status in {
            PlaceholderStatus.CLOUD_PLACEHOLDER,
            PlaceholderStatus.UNSUPPORTED_PLATFORM,
        }:
            raise ValueError(
                "local roots cannot report cloud-placeholder probe states"
            )


class CloudPlaceholderProbe(Protocol):
    """Provider-neutral metadata probe that never reads candidate bytes."""

    @property
    def probe_id(self) -> str: ...

    def support(
        self,
        *,
        root_alias: str,
    ) -> PlaceholderProbeSupport: ...

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus: ...


class UnsupportedCloudPlaceholderProbe:
    """Default probe: no native platform semantics are implemented."""

    probe_id = "unsupported-default-placeholder-probe-v1"

    def support(
        self,
        *,
        root_alias: str,
    ) -> PlaceholderProbeSupport:
        validate_root_alias(root_alias)
        return PlaceholderProbeSupport.UNSUPPORTED_PLATFORM

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus:
        validate_root_alias(root_alias)
        validate_relative_path(relative_path)
        return PlaceholderStatus.UNSUPPORTED_PLATFORM


UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE = UnsupportedCloudPlaceholderProbe()


def _validate_probe_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value) is None
    ):
        raise ValueError("placeholder probe identity is invalid")
    return value


def authorize_root_preflight(
    *,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None,
) -> RootPreflightEvidence:
    """Validate root capability before touching its filesystem path."""
    validate_root_alias(root_alias)
    if not isinstance(storage_class, RootStorageClass):
        raise ValueError("root storage class must be explicit")
    if storage_class is RootStorageClass.LOCAL:
        if placeholder_probe is not None:
            raise ValueError("local roots must not supply a cloud probe")
        return RootPreflightEvidence(
            root_alias=root_alias,
            storage_class=storage_class,
            probe_id="local-root-no-cloud-probe-v1",
            probe_support=None,
        )
    probe = placeholder_probe or UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE
    try:
        probe_id = _validate_probe_id(probe.probe_id)
        support = probe.support(root_alias=root_alias)
    except Exception as error:
        observation = PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id="ambiguous-cloud-placeholder-probe-v1",
            status=PlaceholderStatus.AMBIGUOUS,
        )
        raise PlaceholderPreflightError(observation) from error
    if not isinstance(support, PlaceholderProbeSupport):
        observation = PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id=probe_id,
            status=PlaceholderStatus.AMBIGUOUS,
        )
        raise PlaceholderPreflightError(observation)
    if support is PlaceholderProbeSupport.UNSUPPORTED_PLATFORM:
        observation = PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id=probe_id,
            status=PlaceholderStatus.UNSUPPORTED_PLATFORM,
        )
        raise PlaceholderPreflightError(observation)
    return RootPreflightEvidence(
        root_alias=root_alias,
        storage_class=storage_class,
        probe_id=probe_id,
        probe_support=support,
    )


@dataclass(frozen=True)
class FileObservation:
    """One streaming observation of a confined regular file."""

    byte_size: int
    sha256: str
    prefix: bytes


def validate_citekey(value: object, *, field: str = "citekey") -> str:
    """Return one portable, filesystem-safe citation key."""
    if not isinstance(value, str) or not value:
        raise PathSafetyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise PathSafetyError(f"{field} must use NFC normalization")
    if len(value) > _CITEKEY_MAX_LENGTH:
        raise PathSafetyError(f"{field} exceeds the portable length limit")
    if not value[0].isascii() or not value[0].isalpha():
        raise PathSafetyError(f"{field} must start with an ASCII letter")
    if any(character not in _CITEKEY_ASCII for character in value):
        raise PathSafetyError(
            f"{field} may contain only ASCII letters, numbers, period, "
            "underscore, or hyphen"
        )
    if value.endswith("."):
        raise PathSafetyError(f"{field} must not end with a period")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise PathSafetyError(f"{field} is a reserved portable filename")
    return value


def validate_root_alias(value: object, *, field: str = "root_alias") -> str:
    """Return one portable root-alias segment."""
    if not isinstance(value, str) or not value:
        raise PathSafetyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise PathSafetyError(f"{field} must use NFC normalization")
    if len(value) > 100:
        raise PathSafetyError(f"{field} exceeds the portable length limit")
    if "/" in value or "\\" in value:
        raise PathSafetyError(f"{field} must be one portable path segment")
    _validate_portable_segment(value, field=field)
    return value


def validate_relative_path(
    value: str | PurePosixPath,
    *,
    field: str = "relative_path",
) -> PurePosixPath:
    """Return a normalized portable relative path without traversal."""
    raw = value.as_posix() if isinstance(value, PurePosixPath) else value
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise PathSafetyError(
            f"{field} must be a normalized portable relative path"
        )
    if raw != unicodedata.normalize("NFC", raw):
        raise PathSafetyError(f"{field} must use NFC normalization")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise PathSafetyError(
            f"{field} must be normalized, relative, and traversal-free"
        )
    for part in path.parts:
        _validate_portable_segment(part, field=field)
    return path


def _validate_portable_segment(value: str, *, field: str) -> None:
    if value in {"", ".", ".."}:
        raise PathSafetyError(f"{field} contains an invalid path segment")
    if value.endswith((" ", ".")):
        raise PathSafetyError(
            f"{field} contains a segment ending with space or period"
        )
    if any(
        ord(character) < 32 or character in _PORTABLE_FORBIDDEN
        for character in value
    ):
        raise PathSafetyError(
            f"{field} contains a nonportable filename character"
        )
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise PathSafetyError(f"{field} contains a reserved filename segment")


@dataclass(frozen=True)
class AuthorizedRoot:
    """A directory identity used for descriptor-confined filesystem access."""

    path: Path
    label: str
    device: int
    inode: int
    preflight_evidence: RootPreflightEvidence
    placeholder_probe: CloudPlaceholderProbe | None

    @classmethod
    def existing(
        cls,
        path: Path,
        *,
        label: str,
        root_alias: str,
        storage_class: RootStorageClass,
        placeholder_probe: CloudPlaceholderProbe | None = None,
    ) -> AuthorizedRoot:
        """Bind an existing real directory as an authorized root."""
        preflight = authorize_root_preflight(
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        supplied = path.expanduser()
        if supplied.is_symlink():
            raise PathSafetyError(f"{label} must not be a symlink")
        try:
            resolved = supplied.resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as error:
            raise PathSafetyError(f"{label} does not exist") from error
        if not resolved.is_dir():
            raise PathSafetyError(f"{label} must be a directory")
        descriptor = _open_directory(resolved, label=label)
        try:
            metadata = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        return cls(
            path=resolved,
            label=label,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            preflight_evidence=preflight,
            placeholder_probe=(
                placeholder_probe
                if storage_class is RootStorageClass.CLOUD_BACKED
                else None
            ),
        )

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        label: str,
        root_alias: str,
        storage_class: RootStorageClass,
        placeholder_probe: CloudPlaceholderProbe | None = None,
    ) -> AuthorizedRoot:
        """Create, then bind, a real authorized directory."""
        if storage_class is RootStorageClass.CLOUD_BACKED:
            raise CloudRootMutationError(
                "cloud-backed root creation requires external authorization"
            )
        authorize_root_preflight(
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        supplied = path.expanduser()
        if supplied.is_symlink():
            raise PathSafetyError(f"{label} must not be a symlink")
        try:
            supplied.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PathSafetyError(f"cannot create {label}") from error
        return cls.existing(
            supplied,
            label=label,
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )

    def child_path(self, relative: str | PurePosixPath) -> Path:
        """Render a validated child path for reporting only."""
        safe = validate_relative_path(relative)
        return self.path.joinpath(*safe.parts)

    def state(
        self,
        relative: str | PurePosixPath,
    ) -> Literal["missing", "regular", "directory"]:
        """Classify a confined child without following symlinks."""
        safe = validate_relative_path(relative)
        try:
            parent = self._open_parent(safe.parts[:-1])
        except FileNotFoundError:
            return "missing"
        try:
            try:
                metadata = os.stat(
                    safe.parts[-1], dir_fd=parent, follow_symlinks=False
                )
            except FileNotFoundError:
                return "missing"
            if stat.S_ISLNK(metadata.st_mode):
                raise PathSafetyError(
                    f"{self.label} child must not be a symlink: {safe}"
                )
            if stat.S_ISREG(metadata.st_mode):
                return "regular"
            if stat.S_ISDIR(metadata.st_mode):
                return "directory"
            raise PathSafetyError(
                f"{self.label} child is not a regular file or directory: {safe}"
            )
        finally:
            os.close(parent)

    def preflight_file(
        self,
        relative: str | PurePosixPath,
    ) -> PlaceholderObservation:
        """Classify a candidate using metadata only before opening its bytes."""
        safe = validate_relative_path(relative)
        evidence = self.preflight_evidence
        if evidence.storage_class is RootStorageClass.CLOUD_BACKED:
            probe = self.placeholder_probe
            if probe is None:
                return self._preflight_observation(
                    safe, PlaceholderStatus.UNSUPPORTED_PLATFORM
                )
            try:
                status = probe.observe(
                    root_alias=evidence.root_alias,
                    relative_path=safe,
                )
            except Exception:
                return self._preflight_observation(
                    safe, PlaceholderStatus.AMBIGUOUS
                )
            if not isinstance(status, PlaceholderStatus):
                return self._preflight_observation(
                    safe, PlaceholderStatus.AMBIGUOUS
                )
            if status is not PlaceholderStatus.ORDINARY_FILE:
                return self._preflight_observation(safe, status)
        try:
            parent = self._open_parent(safe.parts[:-1])
        except FileNotFoundError:
            return self._preflight_observation(safe, PlaceholderStatus.MISSING)
        except PermissionError:
            return self._preflight_observation(
                safe, PlaceholderStatus.ACCESS_CONTROLLED
            )
        try:
            try:
                metadata = os.stat(
                    safe.parts[-1],
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return self._preflight_observation(
                    safe, PlaceholderStatus.MISSING
                )
            except PermissionError:
                return self._preflight_observation(
                    safe, PlaceholderStatus.ACCESS_CONTROLLED
                )
            if stat.S_ISLNK(metadata.st_mode):
                raise PathSafetyError(
                    f"{self.label} child must not be a symlink: {safe}"
                )
            if not stat.S_ISREG(metadata.st_mode):
                return self._preflight_observation(
                    safe, PlaceholderStatus.AMBIGUOUS
                )
            read_bits = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            if metadata.st_mode & read_bits == 0:
                return self._preflight_observation(
                    safe, PlaceholderStatus.UNREADABLE
                )
            return self._preflight_observation(
                safe, PlaceholderStatus.ORDINARY_FILE
            )
        finally:
            os.close(parent)

    def require_readable_file(
        self,
        relative: str | PurePosixPath,
    ) -> PlaceholderObservation:
        """Fail closed unless metadata preflight permits byte access."""
        observation = self.preflight_file(relative)
        if observation.status is PlaceholderStatus.ORDINARY_FILE:
            return observation
        if observation.storage_class is RootStorageClass.CLOUD_BACKED:
            raise PlaceholderPreflightError(observation)
        if observation.status is PlaceholderStatus.MISSING:
            raise FileNotFoundError(observation.relative_path)
        if observation.status in {
            PlaceholderStatus.ACCESS_CONTROLLED,
            PlaceholderStatus.UNREADABLE,
        }:
            raise PermissionError(
                "candidate byte access denied by metadata preflight"
            )
        raise PlaceholderPreflightError(observation)

    def _preflight_observation(
        self,
        relative: PurePosixPath,
        status: PlaceholderStatus,
    ) -> PlaceholderObservation:
        evidence = self.preflight_evidence
        return PlaceholderObservation(
            root_alias=evidence.root_alias,
            relative_path=relative.as_posix(),
            storage_class=evidence.storage_class,
            probe_id=evidence.probe_id,
            status=status,
        )

    def read_bytes(
        self,
        relative: str | PurePosixPath,
        *,
        max_bytes: int = _DEFAULT_READ_MAX_BYTES,
    ) -> bytes:
        """Read one regular file through no-follow directory descriptors."""
        safe = validate_relative_path(relative)
        self.require_readable_file(safe)
        parent = self._open_parent(safe.parts[:-1])
        descriptor = -1
        try:
            try:
                descriptor = os.open(safe.parts[-1], _FILE_FLAGS, dir_fd=parent)
            except OSError as error:
                _raise_path_error(
                    error,
                    f"cannot safely open {self.label} child: {safe}",
                )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise PathSafetyError(
                    f"{self.label} child is not a regular file: {safe}"
                )
            if (
                type(max_bytes) is not int
                or not 0 <= max_bytes <= _DEFAULT_READ_MAX_BYTES
            ):
                raise ValueError(
                    "max_bytes must be a nonnegative integer within the "
                    "bounded-read ceiling"
                )
            if before.st_size > max_bytes:
                raise PathLimitError(
                    resource=f"{self.label} child {safe}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise PathLimitError(
                    resource=f"{self.label} child {safe}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=len(data),
                )
            after = os.fstat(descriptor)
            if (
                _file_identity(before) != _file_identity(after)
                or len(data) != after.st_size
            ):
                raise PathSafetyError(
                    f"{self.label} child changed while it was read: {safe}"
                )
            self._require_open_leaf_identity(
                parent=parent,
                leaf=safe.parts[-1],
                opened=after,
                safe=safe,
                operation="read",
            )
            return data
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)

    def read_text(
        self,
        relative: str | PurePosixPath,
        *,
        encoding: str = "utf-8",
        max_bytes: int = _DEFAULT_READ_MAX_BYTES,
    ) -> str:
        """Read and decode one confined regular file."""
        return self.read_bytes(relative, max_bytes=max_bytes).decode(encoding)

    def observe_file(
        self,
        relative: str | PurePosixPath,
        *,
        max_bytes: int,
        prefix_bytes: int = 0,
        chunk_bytes: int = 1_048_576,
    ) -> FileObservation:
        """Hash and size one file in bounded memory through one descriptor."""
        if (
            not 0 <= max_bytes <= _MAX_STREAMED_FILE_BYTES
            or not 0 <= prefix_bytes <= 1_000_000
            or not 0 < chunk_bytes <= 8_000_000
        ):
            raise ValueError("file observation limits are invalid")
        safe = validate_relative_path(relative)
        self.require_readable_file(safe)
        parent = self._open_parent(safe.parts[:-1])
        descriptor = -1
        try:
            try:
                descriptor = os.open(safe.parts[-1], _FILE_FLAGS, dir_fd=parent)
            except OSError as error:
                _raise_path_error(
                    error,
                    f"cannot safely open {self.label} child: {safe}",
                )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise PathSafetyError(
                    f"{self.label} child is not a regular file: {safe}"
                )
            if before.st_size > max_bytes:
                raise PathLimitError(
                    resource=f"{self.label} child {safe}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            digest = hashlib.sha256()
            prefix = bytearray()
            total = 0
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while True:
                    remaining = max_bytes - total
                    block = stream.read(min(chunk_bytes, remaining + 1))
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise PathLimitError(
                            resource=f"{self.label} child {safe}",
                            limit_name="max_file_bytes",
                            limit=max_bytes,
                            observed=total,
                        )
                    digest.update(block)
                    if len(prefix) < prefix_bytes:
                        prefix.extend(block[: prefix_bytes - len(prefix)])
            after = os.fstat(descriptor)
            if _file_identity(before) != _file_identity(after) or total != (
                after.st_size
            ):
                raise PathSafetyError(
                    f"{self.label} child changed while it was observed: {safe}"
                )
            self._require_open_leaf_identity(
                parent=parent,
                leaf=safe.parts[-1],
                opened=after,
                safe=safe,
                operation="observed",
            )
            return FileObservation(
                byte_size=total,
                sha256=digest.hexdigest(),
                prefix=bytes(prefix),
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)

    def _require_open_leaf_identity(
        self,
        *,
        parent: int,
        leaf: str,
        opened: os.stat_result,
        safe: PurePosixPath,
        operation: str,
    ) -> None:
        """Require the pathname to still name the opened stable inode."""
        try:
            current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            raise PathSafetyError(
                f"{self.label} child changed or was replaced while it was "
                f"{operation}: {safe}"
            ) from error
        if not stat.S_ISREG(current.st_mode) or _file_identity(
            current
        ) != _file_identity(opened):
            raise PathSafetyError(
                f"{self.label} child changed or was replaced while it was "
                f"{operation}: {safe}"
            )

    def iter_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        reject_directories: bool = False,
        max_files: int | None = None,
        max_entries: int | None = None,
        max_depth: int | None = None,
    ) -> tuple[PurePosixPath, ...]:
        """List regular files deterministically without following symlinks."""
        for name, value in (
            ("max_files", max_files),
            ("max_entries", max_entries),
            ("max_depth", max_depth),
        ):
            ceiling = (
                _MAX_DIRECTORY_DEPTH
                if name == "max_depth"
                else _MAX_DIRECTORY_ENTRIES
            )
            if value is not None and not 0 < value <= ceiling:
                raise ValueError(
                    f"{name} must be positive, no greater than {ceiling}, "
                    "or null"
                )
        max_files = _MAX_DIRECTORY_ENTRIES if max_files is None else max_files
        max_entries = (
            _MAX_DIRECTORY_ENTRIES if max_entries is None else max_entries
        )
        max_depth = _MAX_DIRECTORY_DEPTH if max_depth is None else max_depth
        root = self._open_root()
        try:
            found: list[PurePosixPath] = []
            entries_seen = [0]
            self._walk(
                root,
                prefix=(),
                suffix=suffix,
                recursive=recursive,
                reject_directories=reject_directories,
                found=found,
                entries_seen=entries_seen,
                max_files=max_files,
                max_entries=max_entries,
                max_depth=max_depth,
            )
        finally:
            os.close(root)
        return tuple(sorted(found, key=lambda item: item.as_posix()))

    def create_directory(
        self,
        relative: str | PurePosixPath,
    ) -> AuthorizedRoot:
        """Create and bind one confined child directory."""
        self._require_local_mutation()
        safe = validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        child = -1
        try:
            os.mkdir(safe.parts[-1], mode=0o700, dir_fd=parent)
            child = os.open(safe.parts[-1], _DIRECTORY_FLAGS, dir_fd=parent)
            metadata = os.fstat(child)
            os.fsync(parent)
        except FileExistsError:
            raise FileExistsError(self.child_path(safe)) from None
        except OSError as error:
            _raise_path_error(
                error,
                f"cannot safely create {self.label} child directory: {safe}",
            )
        finally:
            if child >= 0:
                os.close(child)
            os.close(parent)
        return AuthorizedRoot(
            path=self.child_path(safe),
            label=f"{self.label} child {safe}",
            device=metadata.st_dev,
            inode=metadata.st_ino,
            preflight_evidence=self.preflight_evidence,
            placeholder_probe=self.placeholder_probe,
        )

    def rename_child(
        self,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
    ) -> Path:
        """Rename a confined child while refusing an existing destination."""
        self._require_local_mutation()
        safe_source = validate_relative_path(source, field="source")
        safe_destination = validate_relative_path(
            destination,
            field="destination",
        )
        if safe_source.parts[:-1] != safe_destination.parts[:-1]:
            raise PathSafetyError("rename source and destination must be peers")
        parent = self._open_parent(safe_source.parts[:-1])
        try:
            try:
                os.stat(
                    safe_destination.parts[-1],
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(self.child_path(safe_destination))
            os.rename(
                safe_source.parts[-1],
                safe_destination.parts[-1],
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            os.fsync(parent)
        finally:
            os.close(parent)
        return self.child_path(safe_destination)

    def write_bytes(
        self,
        relative: str | PurePosixPath,
        content: bytes,
        *,
        replace: bool,
    ) -> Path:
        """Atomically write one confined file without following symlinks."""
        self._require_local_mutation()
        safe = validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        leaf = safe.parts[-1]
        temporary = f".koios-{leaf}-{secrets.token_hex(12)}.tmp"
        descriptor = -1
        try:
            try:
                existing = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if stat.S_ISLNK(existing.st_mode):
                    raise PathSafetyError(
                        f"{self.label} destination must not be a symlink: "
                        f"{safe}"
                    )
                if not stat.S_ISREG(existing.st_mode):
                    raise PathSafetyError(
                        f"{self.label} destination is not a regular file: "
                        f"{safe}"
                    )
                if not replace:
                    raise FileExistsError(self.child_path(safe))
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent,
            )
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = -1
            if replace:
                os.replace(
                    temporary,
                    leaf,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
            else:
                try:
                    os.link(
                        temporary,
                        leaf,
                        src_dir_fd=parent,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    raise FileExistsError(self.child_path(safe)) from None
                finally:
                    os.unlink(temporary, dir_fd=parent)
            os.fsync(parent)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(parent)
        return self.child_path(safe)

    def copy_file_from(
        self,
        source_root: AuthorizedRoot,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
        *,
        max_bytes: int,
        expected_sha256: str,
        expected_size: int,
        chunk_bytes: int = 1_048_576,
    ) -> Path:
        """Stream a verified source into a new atomic destination file."""
        self._require_local_mutation()
        if (
            not 0 <= max_bytes <= _MAX_STREAMED_FILE_BYTES
            or expected_size < 0
            or not 0 < chunk_bytes <= 8_000_000
            or len(expected_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_sha256
            )
        ):
            raise ValueError(
                "file-copy limits or expected identity are invalid"
            )
        if expected_size > max_bytes:
            raise PathLimitError(
                resource=f"{source_root.label} expected source",
                limit_name="max_file_bytes",
                limit=max_bytes,
                observed=expected_size,
            )
        safe_source = validate_relative_path(source, field="source")
        source_root.require_readable_file(safe_source)
        safe_destination = validate_relative_path(
            destination,
            field="destination",
        )
        source_parent = source_root._open_parent(safe_source.parts[:-1])
        destination_parent = self._open_parent(safe_destination.parts[:-1])
        source_descriptor = -1
        destination_descriptor = -1
        temporary = (
            f".koios-{safe_destination.parts[-1]}-{secrets.token_hex(12)}.tmp"
        )
        try:
            try:
                existing = os.stat(
                    safe_destination.parts[-1],
                    dir_fd=destination_parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None
            if existing is not None:
                raise FileExistsError(self.child_path(safe_destination))
            try:
                source_descriptor = os.open(
                    safe_source.parts[-1],
                    _FILE_FLAGS,
                    dir_fd=source_parent,
                )
            except OSError as error:
                _raise_path_error(
                    error,
                    f"cannot safely open {source_root.label} child: "
                    f"{safe_source}",
                )
            before = os.fstat(source_descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise PathSafetyError(
                    f"{source_root.label} child is not a regular file: "
                    f"{safe_source}"
                )
            if before.st_size > max_bytes:
                raise PathLimitError(
                    resource=f"{source_root.label} child {safe_source}",
                    limit_name="max_file_bytes",
                    limit=max_bytes,
                    observed=before.st_size,
                )
            destination_descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=destination_parent,
            )
            digest = hashlib.sha256()
            total = 0
            with (
                os.fdopen(source_descriptor, "rb", closefd=False) as reader,
                os.fdopen(
                    destination_descriptor,
                    "wb",
                    closefd=False,
                ) as writer,
            ):
                while True:
                    block = reader.read(chunk_bytes)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise PathLimitError(
                            resource=(
                                f"{source_root.label} child {safe_source}"
                            ),
                            limit_name="max_file_bytes",
                            limit=max_bytes,
                            observed=total,
                        )
                    digest.update(block)
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            after = os.fstat(source_descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or total != after.st_size:
                raise PathSafetyError(
                    f"{source_root.label} child changed while copied: "
                    f"{safe_source}"
                )
            if total != expected_size or digest.hexdigest() != expected_sha256:
                raise PathSafetyError(
                    "source identity changed after its recorded observation"
                )
            os.close(destination_descriptor)
            destination_descriptor = -1
            os.link(
                temporary,
                safe_destination.parts[-1],
                src_dir_fd=destination_parent,
                dst_dir_fd=destination_parent,
                follow_symlinks=False,
            )
            os.unlink(temporary, dir_fd=destination_parent)
            os.fsync(destination_parent)
        except BaseException:
            if destination_descriptor >= 0:
                os.close(destination_descriptor)
            try:
                os.unlink(temporary, dir_fd=destination_parent)
            except FileNotFoundError:
                pass
            raise
        finally:
            if source_descriptor >= 0:
                os.close(source_descriptor)
            os.close(source_parent)
            os.close(destination_parent)
        return self.child_path(safe_destination)

    def _require_local_mutation(self) -> None:
        if (
            self.preflight_evidence.storage_class
            is RootStorageClass.CLOUD_BACKED
        ):
            raise CloudRootMutationError(
                "cloud-backed root mutation is outside default behavior"
            )

    def _open_root(self) -> int:
        descriptor = _open_directory(self.path, label=self.label)
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (self.device, self.inode):
            os.close(descriptor)
            raise PathSafetyError(
                f"{self.label} changed after it was authorized"
            )
        return descriptor

    def _open_parent(self, parts: tuple[str, ...]) -> int:
        descriptor = self._open_root()
        try:
            for part in parts:
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except OSError as error:
                    _raise_path_error(
                        error,
                        f"{self.label} path contains a symlink or "
                        f"non-directory component: {part}",
                    )
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _walk(
        self,
        descriptor: int,
        *,
        prefix: tuple[str, ...],
        suffix: str,
        recursive: bool,
        reject_directories: bool,
        found: list[PurePosixPath],
        entries_seen: list[int],
        max_files: int | None,
        max_entries: int | None,
        max_depth: int | None,
    ) -> None:
        if max_depth is not None and len(prefix) > max_depth:
            raise PathLimitError(
                resource=self.label,
                limit_name="max_depth",
                limit=max_depth,
                observed=len(prefix),
            )
        ordered: list[os.DirEntry[str]] = []
        with os.scandir(descriptor) as entries:
            for entry in entries:
                entries_seen[0] += 1
                if max_entries is not None and entries_seen[0] > max_entries:
                    raise PathLimitError(
                        resource=self.label,
                        limit_name="max_entries",
                        limit=max_entries,
                        observed=entries_seen[0],
                    )
                ordered.append(entry)
        ordered.sort(key=lambda item: item.name)
        for entry in ordered:
            relative = PurePosixPath(*prefix, entry.name)
            if entry.is_symlink():
                raise PathSafetyError(
                    f"{self.label} contains a symlink: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                if not recursive:
                    if reject_directories:
                        raise PathSafetyError(
                            f"{self.label} contains an unexpected directory: "
                            f"{relative}"
                        )
                    continue
                try:
                    child = os.open(
                        entry.name, _DIRECTORY_FLAGS, dir_fd=descriptor
                    )
                except OSError as error:
                    _raise_path_error(
                        error,
                        f"cannot safely traverse {self.label}: {relative}",
                    )
                try:
                    self._walk(
                        child,
                        prefix=(*prefix, entry.name),
                        suffix=suffix,
                        recursive=True,
                        reject_directories=reject_directories,
                        found=found,
                        entries_seen=entries_seen,
                        max_files=max_files,
                        max_entries=max_entries,
                        max_depth=max_depth,
                    )
                finally:
                    os.close(child)
                continue
            if entry.is_file(follow_symlinks=False):
                if entry.name.endswith(suffix):
                    found.append(relative)
                    if max_files is not None and len(found) > max_files:
                        raise PathLimitError(
                            resource=self.label,
                            limit_name="max_files",
                            limit=max_files,
                            observed=len(found),
                        )
                continue
            raise PathSafetyError(
                f"{self.label} contains an unsupported filesystem object: "
                f"{relative}"
            )


def read_path_bytes(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    max_bytes: int = _DEFAULT_READ_MAX_BYTES,
) -> bytes:
    """Read an explicitly classified file through its authorized parent."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.read_bytes(path.name, max_bytes=max_bytes)


def observe_path_file(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    max_bytes: int,
    prefix_bytes: int = 0,
) -> FileObservation:
    """Observe an explicitly classified file without loading it into memory."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.observe_file(
        path.name,
        max_bytes=max_bytes,
        prefix_bytes=prefix_bytes,
    )


def read_path_text(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    encoding: str = "utf-8",
    max_bytes: int = _DEFAULT_READ_MAX_BYTES,
) -> str:
    """Read an explicitly classified text file without following symlinks."""
    return read_path_bytes(
        path,
        label=label,
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
        max_bytes=max_bytes,
    ).decode(encoding)


def write_path_bytes(
    path: Path,
    content: bytes,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    replace: bool,
) -> Path:
    """Write through an explicitly classified authorized parent."""
    root = AuthorizedRoot.create(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    return root.write_bytes(path.name, content, replace=replace)


def assert_safe_explicit_path(
    path: Path,
    *,
    label: str,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
) -> Path:
    """Validate a classified path for an external library."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent,
        label=f"{label} parent",
        root_alias=root_alias,
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    state = root.state(path.name)
    if state == "regular":
        root.require_readable_file(path.name)
    if state not in {"missing", "regular"}:
        raise PathSafetyError(f"{label} must be a regular file or missing")
    return root.child_path(path.name)


def _file_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _open_directory(path: Path, *, label: str) -> int:
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
    except OSError as error:
        _raise_path_error(error, f"cannot safely open {label}")
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise PathSafetyError(f"{label} must be a directory")
    return descriptor


def _raise_path_error(error: OSError, message: str) -> Never:
    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise PathSafetyError(message) from error
    raise error
