from __future__ import annotations

from enum import StrEnum


class RootStorageClass(StrEnum):
    """Operator-declared storage semantics for an authorized root."""

    LOCAL = "local"
    CLOUD_BACKED = "cloud-backed"
