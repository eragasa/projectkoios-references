"""Cloud-placeholder preflight models and probe boundaries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol, final

from projectkoios.base import DataObjectModel
from projectkoios.references.path_safety import errors, validation


class RootStorageClass(StrEnum):
    """Operator-declared storage semantics for an authorized root."""

    LOCAL = "local"
    CLOUD_BACKED = "cloud-backed"


class PlaceholderProbeSupport(StrEnum):
    """Whether a probe can safely classify this cloud-backed root."""

    SUPPORTED = "supported"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    AMBIGUOUS = "ambiguous"


class PlaceholderStatus(StrEnum):
    """A metadata-only classification made before candidate byte access."""

    ORDINARY_FILE = "ordinary-file"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    MISSING = "missing"
    ACCESS_CONTROLLED = "access-controlled"
    UNREADABLE = "unreadable"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    AMBIGUOUS = "ambiguous"
    FILESYSTEM_BOUNDARY = "filesystem-boundary"


class PlaceholderProbeIdentity:
    """Own the bounded grammar for placeholder-probe identities."""

    __slots__ = ()

    @staticmethod
    def validate(*, value: object) -> str:
        """Return one valid placeholder-probe identity."""
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value) is None
        ):
            raise ValueError("placeholder probe identity is invalid")
        return value


@final
@dataclass(frozen=True, slots=True)
class RootPreflightEvidence(DataObjectModel):
    """Privacy-reduced evidence for one declared root capability."""

    root_alias: str
    storage_class: RootStorageClass
    probe_id: str
    probe_support: PlaceholderProbeSupport | None

    def __post_init__(self) -> None:
        validation.validate_root_alias(self.root_alias)
        PlaceholderProbeIdentity.validate(value=self.probe_id)
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


@final
@dataclass(frozen=True, slots=True)
class PlaceholderObservation(DataObjectModel):
    """A privacy-reduced, metadata-only candidate-path observation."""

    root_alias: str
    relative_path: str | None
    storage_class: RootStorageClass
    probe_id: str
    status: PlaceholderStatus

    def __post_init__(self) -> None:
        validation.validate_root_alias(self.root_alias)
        PlaceholderProbeIdentity.validate(value=self.probe_id)
        if not isinstance(self.storage_class, RootStorageClass):
            raise ValueError("root storage class must be explicit")
        if not isinstance(self.status, PlaceholderStatus):
            raise ValueError("placeholder status is invalid")
        if self.relative_path is not None:
            validation.validate_relative_path(self.relative_path)
        if self.storage_class is RootStorageClass.LOCAL and self.status in {
            PlaceholderStatus.CLOUD_PLACEHOLDER,
            PlaceholderStatus.UNSUPPORTED_PLATFORM,
        }:
            raise ValueError(
                "local roots cannot report cloud-placeholder probe states"
            )


class PlaceholderPreflightError(errors.PathSafetyError):
    """Raised when cloud-placeholder safety cannot permit byte access."""

    code = "placeholder-preflight-incomplete"
    coverage_status = "incomplete"

    def __init__(self, observation: PlaceholderObservation) -> None:
        self.observation = observation
        super().__init__(
            "cloud-placeholder preflight refused access: "
            f"{observation.root_alias}/"
            f"{observation.relative_path or '<root>'} "
            f"is {observation.status.value}"
        )

    def to_dict(self) -> dict[str, object]:
        """Return the stable machine-readable failure projection."""
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
        """Return the stable JSON failure projection."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


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
    """Default probe when native platform semantics are unavailable."""

    __slots__ = ()

    probe_id = "unsupported-default-placeholder-probe-v1"

    def support(
        self,
        *,
        root_alias: str,
    ) -> PlaceholderProbeSupport:
        validation.validate_root_alias(root_alias)
        return PlaceholderProbeSupport.UNSUPPORTED_PLATFORM

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus:
        validation.validate_root_alias(root_alias)
        validation.validate_relative_path(relative_path)
        return PlaceholderStatus.UNSUPPORTED_PLATFORM


UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE = UnsupportedCloudPlaceholderProbe()
