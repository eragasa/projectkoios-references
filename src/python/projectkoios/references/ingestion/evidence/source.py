from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceEvidenceSource:
    blob_id: str
    hash_algorithm: str
    content_sha256: str
    byte_length: int
    media_type: str
