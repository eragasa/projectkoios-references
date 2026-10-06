from __future__ import annotations


class IngestionEvidenceError(ValueError):
    """Base error for the strict references-owned evidence consumer."""


class IngestionEvidenceLimitError(IngestionEvidenceError):
    """Raised before untrusted evidence exceeds a deterministic bound."""


class IngestionEvidenceParseError(IngestionEvidenceError):
    """Raised when producer bytes are malformed or unsupported."""


class IngestionEvidenceVerificationError(IngestionEvidenceError):
    """Raised when producer evidence does not match a managed PDF."""
