"""Platform probes and root-preflight authorization."""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from projectkoios.references.path_safety import preflight, validation

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@dataclass(frozen=True, slots=True)
class MacOSFileProviderPlaceholderProbe:
    """Classify macOS File Provider objects using no-follow stat metadata.

    The probe captures one explicitly authorized root at construction.  It
    opens only directory descriptors and obtains leaf metadata with
    ``follow_symlinks=False``; it never opens or reads candidate file bytes.
    """

    root_path: Path
    probe_id = "macos-file-provider-stat-sf-dataless-v1"
    _normalized_root: str = field(init=False, repr=False, compare=False)
    _root_identity: tuple[int, int] | None = field(
        init=False,
        default=None,
        repr=False,
        compare=False,
    )

    @staticmethod
    def _normalized_runtime_root(*, path: Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path.expanduser())))

    def __post_init__(self) -> None:
        if not isinstance(self.root_path, Path):
            raise ValueError("macOS File Provider root must be a Path")
        object.__setattr__(
            self,
            "_normalized_root",
            self._normalized_runtime_root(path=self.root_path),
        )

    def matches_root_path(self, root_path: Path) -> bool:
        """Return whether a declaration names this exact captured root."""
        return (
            isinstance(root_path, Path)
            and self._normalized_runtime_root(path=root_path)
            == self._normalized_root
        )

    def bind_authorized_root(
        self,
        root_path: Path,
        *,
        device: int,
        inode: int,
    ) -> bool:
        """Bind the probe to the same directory identity as byte access."""
        if not self.matches_root_path(root_path):
            return False
        descriptor = -1
        try:
            descriptor = os.open(self._normalized_root, _DIRECTORY_FLAGS)
            metadata = os.fstat(descriptor)
        except OSError:
            return False
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if identity != (device, inode):
            return False
        prior = self._root_identity
        if prior is not None and prior != identity:
            return False
        object.__setattr__(self, "_root_identity", identity)
        return True

    def support(
        self,
        *,
        root_alias: str,
    ) -> preflight.PlaceholderProbeSupport:
        validation.validate_root_alias(root_alias)
        if sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"):
            return preflight.PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
        return preflight.PlaceholderProbeSupport.SUPPORTED

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> preflight.PlaceholderStatus:
        validation.validate_root_alias(root_alias)
        safe = validation.validate_relative_path(relative_path)
        if (
            self.support(root_alias=root_alias)
            is not preflight.PlaceholderProbeSupport.SUPPORTED
        ):
            return preflight.PlaceholderStatus.UNSUPPORTED_PLATFORM
        descriptor = -1
        try:
            try:
                descriptor = os.open(
                    self._normalized_root,
                    _DIRECTORY_FLAGS,
                )
            except FileNotFoundError:
                return preflight.PlaceholderStatus.MISSING
            except PermissionError:
                return preflight.PlaceholderStatus.ACCESS_CONTROLLED
            except OSError:
                return preflight.PlaceholderStatus.AMBIGUOUS
            root_metadata = os.fstat(descriptor)
            if (
                self._root_identity is None
                or (
                    root_metadata.st_dev,
                    root_metadata.st_ino,
                )
                != self._root_identity
            ):
                return preflight.PlaceholderStatus.AMBIGUOUS
            for part in safe.parts[:-1]:
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except FileNotFoundError:
                    return preflight.PlaceholderStatus.MISSING
                except PermissionError:
                    return preflight.PlaceholderStatus.ACCESS_CONTROLLED
                except OSError:
                    return preflight.PlaceholderStatus.AMBIGUOUS
                try:
                    child_metadata = os.fstat(child)
                except OSError:
                    os.close(child)
                    return preflight.PlaceholderStatus.AMBIGUOUS
                if child_metadata.st_dev != self._root_identity[0]:
                    os.close(child)
                    return preflight.PlaceholderStatus.FILESYSTEM_BOUNDARY
                os.close(descriptor)
                descriptor = child
            try:
                metadata = os.stat(
                    safe.parts[-1],
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return preflight.PlaceholderStatus.MISSING
            except PermissionError:
                return preflight.PlaceholderStatus.ACCESS_CONTROLLED
            except OSError:
                return preflight.PlaceholderStatus.AMBIGUOUS
            if metadata.st_dev != self._root_identity[0]:
                return preflight.PlaceholderStatus.FILESYSTEM_BOUNDARY
            if not stat.S_ISREG(metadata.st_mode):
                return preflight.PlaceholderStatus.AMBIGUOUS
            read_bits = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            if metadata.st_mode & read_bits == 0:
                return preflight.PlaceholderStatus.UNREADABLE
            flags = getattr(metadata, "st_flags", None)
            sf_dataless = getattr(stat, "SF_DATALESS", None)
            if type(flags) is not int or type(sf_dataless) is not int:
                return preflight.PlaceholderStatus.AMBIGUOUS
            if flags & sf_dataless:
                return preflight.PlaceholderStatus.CLOUD_PLACEHOLDER
            return preflight.PlaceholderStatus.ORDINARY_FILE
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def authorize_root_preflight(
    *,
    root_alias: str,
    storage_class: preflight.RootStorageClass,
    placeholder_probe: preflight.CloudPlaceholderProbe | None,
) -> preflight.RootPreflightEvidence:
    """Validate root capability before touching its filesystem path."""
    validation.validate_root_alias(root_alias)
    if not isinstance(storage_class, preflight.RootStorageClass):
        raise ValueError("root storage class must be explicit")
    if storage_class is preflight.RootStorageClass.LOCAL:
        if placeholder_probe is not None:
            raise ValueError("local roots must not supply a cloud probe")
        return preflight.RootPreflightEvidence(
            root_alias=root_alias,
            storage_class=storage_class,
            probe_id="local-root-no-cloud-probe-v1",
            probe_support=None,
        )
    probe = placeholder_probe or preflight.UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE
    try:
        probe_id = preflight.PlaceholderProbeIdentity.validate(
            value=probe.probe_id
        )
        support = probe.support(root_alias=root_alias)
    except Exception as error:
        observation = preflight.PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id="ambiguous-cloud-placeholder-probe-v1",
            status=preflight.PlaceholderStatus.AMBIGUOUS,
        )
        raise preflight.PlaceholderPreflightError(observation) from error
    if not isinstance(support, preflight.PlaceholderProbeSupport):
        observation = preflight.PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id=probe_id,
            status=preflight.PlaceholderStatus.AMBIGUOUS,
        )
        raise preflight.PlaceholderPreflightError(observation)
    if support is not preflight.PlaceholderProbeSupport.SUPPORTED:
        status = (
            preflight.PlaceholderStatus.UNSUPPORTED_PLATFORM
            if support is preflight.PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
            else preflight.PlaceholderStatus.AMBIGUOUS
        )
        observation = preflight.PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id=probe_id,
            status=status,
        )
        raise preflight.PlaceholderPreflightError(observation)
    return preflight.RootPreflightEvidence(
        root_alias=root_alias,
        storage_class=storage_class,
        probe_id=probe_id,
        probe_support=support,
    )
