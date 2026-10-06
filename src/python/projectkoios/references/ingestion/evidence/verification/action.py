from __future__ import annotations

from ..error import IngestionEvidenceVerificationError
from ..json.decoding import (
    require_nonnegative_int,
    require_sha256,
    require_text,
)
from ..media import SOURCE_MEDIA_TYPE
from ..parsing.action import parse_reference_evidence
from ..record.aggregate import ReferenceEvidenceRecord


def verify_reference_evidence_source(
    record: ReferenceEvidenceRecord,
    *,
    source_sha256: str,
    source_byte_length: int,
    source_media_type: str = SOURCE_MEDIA_TYPE,
) -> None:
    """Verify source identity without claiming independent derivation review."""

    if not isinstance(record, ReferenceEvidenceRecord):
        raise TypeError("record must be ReferenceEvidenceRecord")
    reparsed = parse_reference_evidence(record.to_bytes())
    if reparsed != record:
        raise IngestionEvidenceVerificationError(
            "reference evidence object differs from canonical replay"
        )
    digest = require_sha256(source_sha256, "expected source_sha256")
    byte_length = require_nonnegative_int(
        source_byte_length, "expected source_byte_length"
    )
    media_type = require_text(source_media_type, "expected source_media_type")
    source = record.source
    if (
        source.content_sha256 != digest
        or source.byte_length != byte_length
        or source.media_type != media_type
        or source.blob_id != f"blob:sha256:{digest}"
    ):
        raise IngestionEvidenceVerificationError(
            "reference evidence does not match the managed PDF identity"
        )
