from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceEvidenceArtifact:
    media_type: str
    sha256: str
    byte_length: int
