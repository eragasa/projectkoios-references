"""Descriptor-confined path validation, observation, and publication."""

from __future__ import annotations

from projectkoios.references.path_safety.errors import (
    CloudRootMutationError,
    FilesystemBoundaryError,
    PathLimitError,
    PathSafetyError,
)
from projectkoios.references.path_safety.inventory import (
    FileObservation,
    FilesystemInventory,
    FilesystemInventoryIssue,
    FilesystemIssueKind,
)
from projectkoios.references.path_safety.paths import (
    assert_safe_explicit_path,
    observe_path_file,
    read_path_bytes,
    read_path_text,
    write_path_bytes,
)
from projectkoios.references.path_safety.preflight import (
    UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE,
    CloudPlaceholderProbe,
    PlaceholderObservation,
    PlaceholderPreflightError,
    PlaceholderProbeSupport,
    PlaceholderStatus,
    RootPreflightEvidence,
    RootStorageClass,
    UnsupportedCloudPlaceholderProbe,
)
from projectkoios.references.path_safety.probes import (
    MacOSFileProviderPlaceholderProbe,
    authorize_root_preflight,
)
from projectkoios.references.path_safety.root import AuthorizedRoot
from projectkoios.references.path_safety.validation import (
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

__all__ = [
    "AuthorizedRoot",
    "CloudPlaceholderProbe",
    "CloudRootMutationError",
    "FileObservation",
    "FilesystemBoundaryError",
    "FilesystemInventory",
    "FilesystemInventoryIssue",
    "FilesystemIssueKind",
    "MacOSFileProviderPlaceholderProbe",
    "PathLimitError",
    "PathSafetyError",
    "PlaceholderObservation",
    "PlaceholderPreflightError",
    "PlaceholderProbeSupport",
    "PlaceholderStatus",
    "RootPreflightEvidence",
    "RootStorageClass",
    "UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE",
    "UnsupportedCloudPlaceholderProbe",
    "assert_safe_explicit_path",
    "authorize_root_preflight",
    "observe_path_file",
    "read_path_bytes",
    "read_path_text",
    "validate_citekey",
    "validate_relative_path",
    "validate_root_alias",
    "write_path_bytes",
]
