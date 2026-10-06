from __future__ import annotations

import hashlib
import json


def canonical_reference_evidence_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")


def stable_reference_evidence_id(namespace: str, value: object) -> str:
    content = canonical_reference_evidence_bytes([value])
    return f"{namespace}:sha256:{hashlib.sha256(content).hexdigest()}"
