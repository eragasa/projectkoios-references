from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from projectkoios.references.filesystem.path import validation

from .status import PlaceholderStatus
from .support import PlaceholderProbeSupport


class PlaceholderProbe(Protocol):
    """Preflight support declaration without byte-observation authority."""

    @property
    def probe_id(self) -> str: ...

    def support(self, *, root_alias: str) -> PlaceholderProbeSupport: ...


class CloudPlaceholderProbe(PlaceholderProbe, Protocol):
    """Bound metadata probe that never reads candidate bytes."""

    def observe(
        self, *, root_alias: str, relative_path: PurePosixPath
    ) -> PlaceholderStatus: ...


@runtime_checkable
class RootBoundPlaceholderProbeFactory(PlaceholderProbe, Protocol):
    """Factory that binds observation authority to one root inode."""

    def matches_root_path(self, root_path: Path) -> bool: ...

    def bind_authorized_root(
        self, root_path: Path, *, device: int, inode: int
    ) -> CloudPlaceholderProbe | None:
        """Return a separately bound probe, or ``None`` on mismatch."""
        ...


type RootPlaceholderProbe = (
    CloudPlaceholderProbe | RootBoundPlaceholderProbeFactory
)


class UnsupportedCloudPlaceholderProbe:
    """Default probe when native platform semantics are unavailable."""

    __slots__ = ()
    probe_id = "unsupported-default-placeholder-probe-v1"

    def support(self, *, root_alias: str) -> PlaceholderProbeSupport:
        validation.validate_root_alias(root_alias)
        return PlaceholderProbeSupport.UNSUPPORTED_PLATFORM

    def observe(
        self, *, root_alias: str, relative_path: PurePosixPath
    ) -> PlaceholderStatus:
        validation.validate_root_alias(root_alias)
        validation.validate_relative_path(relative_path)
        return PlaceholderStatus.UNSUPPORTED_PLATFORM


UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE = UnsupportedCloudPlaceholderProbe()
