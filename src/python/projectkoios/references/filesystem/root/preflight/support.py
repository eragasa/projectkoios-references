from __future__ import annotations

from enum import StrEnum


class PlaceholderProbeSupport(StrEnum):
    """Whether a probe can safely classify a cloud-backed root."""

    SUPPORTED = "supported"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    AMBIGUOUS = "ambiguous"
