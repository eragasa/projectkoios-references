"""macOS File Provider placeholder metadata probe."""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from projectkoios.references.filesystem.path import validation
from projectkoios.references.filesystem.root.preflight.probe import (
    CloudPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.status import (
    PlaceholderStatus,
)
from projectkoios.references.filesystem.root.preflight.support import (
    PlaceholderProbeSupport,
)

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@dataclass(frozen=True, slots=True)
class MacOSFileProviderPlaceholderProbe:
    """Unbound factory for one separately bound File Provider probe."""

    root_path: Path
    probe_id = "macos-file-provider-stat-sf-dataless-v1"
    _normalized_root: str = field(init=False, repr=False, compare=False)

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
    ) -> CloudPlaceholderProbe | None:
        """Return an immutable bound probe without mutating this factory."""
        if not self.matches_root_path(root_path):
            return None
        descriptor = -1
        try:
            descriptor = os.open(self._normalized_root, _DIRECTORY_FLAGS)
            metadata = os.fstat(descriptor)
        except OSError:
            return None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (device, inode):
            return None
        return _BoundMacOSFileProviderPlaceholderProbe(
            normalized_root=self._normalized_root,
            root_device=device,
            root_inode=inode,
        )

    def support(
        self,
        *,
        root_alias: str,
    ) -> PlaceholderProbeSupport:
        validation.validate_root_alias(root_alias)
        if sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"):
            return PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
        return PlaceholderProbeSupport.SUPPORTED


@dataclass(frozen=True, slots=True)
class _BoundMacOSFileProviderPlaceholderProbe:
    """Immutable root-identity-bound File Provider metadata capability."""

    normalized_root: str
    root_device: int
    root_inode: int
    probe_id = MacOSFileProviderPlaceholderProbe.probe_id

    def support(
        self,
        *,
        root_alias: str,
    ) -> PlaceholderProbeSupport:
        validation.validate_root_alias(root_alias)
        if sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"):
            return PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
        return PlaceholderProbeSupport.SUPPORTED

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus:
        validation.validate_root_alias(root_alias)
        safe = validation.validate_relative_path(relative_path)
        if (
            self.support(root_alias=root_alias)
            is not PlaceholderProbeSupport.SUPPORTED
        ):
            return PlaceholderStatus.UNSUPPORTED_PLATFORM
        descriptor = -1
        try:
            try:
                descriptor = os.open(self.normalized_root, _DIRECTORY_FLAGS)
            except FileNotFoundError:
                return PlaceholderStatus.MISSING
            except PermissionError:
                return PlaceholderStatus.ACCESS_CONTROLLED
            except OSError:
                return PlaceholderStatus.AMBIGUOUS
            root_metadata = os.fstat(descriptor)
            if (root_metadata.st_dev, root_metadata.st_ino) != (
                self.root_device,
                self.root_inode,
            ):
                return PlaceholderStatus.AMBIGUOUS
            for part in safe.parts[:-1]:
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except FileNotFoundError:
                    return PlaceholderStatus.MISSING
                except PermissionError:
                    return PlaceholderStatus.ACCESS_CONTROLLED
                except OSError:
                    return PlaceholderStatus.AMBIGUOUS
                try:
                    child_metadata = os.fstat(child)
                except OSError:
                    os.close(child)
                    return PlaceholderStatus.AMBIGUOUS
                if child_metadata.st_dev != self.root_device:
                    os.close(child)
                    return PlaceholderStatus.FILESYSTEM_BOUNDARY
                os.close(descriptor)
                descriptor = child
            try:
                metadata = os.stat(
                    safe.parts[-1],
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return PlaceholderStatus.MISSING
            except PermissionError:
                return PlaceholderStatus.ACCESS_CONTROLLED
            except OSError:
                return PlaceholderStatus.AMBIGUOUS
            if metadata.st_dev != self.root_device:
                return PlaceholderStatus.FILESYSTEM_BOUNDARY
            if not stat.S_ISREG(metadata.st_mode):
                return PlaceholderStatus.AMBIGUOUS
            read_bits = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            if metadata.st_mode & read_bits == 0:
                return PlaceholderStatus.UNREADABLE
            flags = getattr(metadata, "st_flags", None)
            sf_dataless = getattr(stat, "SF_DATALESS", None)
            if type(flags) is not int or type(sf_dataless) is not int:
                return PlaceholderStatus.AMBIGUOUS
            if flags & sf_dataless:
                return PlaceholderStatus.CLOUD_PLACEHOLDER
            return PlaceholderStatus.ORDINARY_FILE
        finally:
            if descriptor >= 0:
                os.close(descriptor)
