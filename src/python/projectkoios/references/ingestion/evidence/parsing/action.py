from __future__ import annotations

from ..error import IngestionEvidenceError, IngestionEvidenceParseError
from ..json.decoding import parse_json_bytes
from ..record.aggregate import ReferenceEvidenceRecord
from ..record.decoding import decode_reference_evidence_record
from ..record.serialization import canonical_reference_evidence_bytes
from ..record.validation import validate_reference_evidence_record


def parse_reference_evidence(content: bytes) -> ReferenceEvidenceRecord:
    """Parse canonical bytes under the Proposed generation-1 contract."""

    value = parse_json_bytes(content)
    try:
        canonical = canonical_reference_evidence_bytes(value)
    except (TypeError, UnicodeEncodeError, ValueError, RecursionError) as error:
        raise IngestionEvidenceParseError(
            "reference evidence cannot be canonicalized"
        ) from error
    if canonical != content:
        raise IngestionEvidenceParseError(
            "reference evidence is not canonical JSON"
        )
    try:
        record = decode_reference_evidence_record(value)
        validate_reference_evidence_record(record)
    except IngestionEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise IngestionEvidenceParseError(
            f"reference evidence is invalid: {error}"
        ) from error
    if record.to_bytes() != content:
        raise IngestionEvidenceParseError(
            "reference evidence replay differs from producer bytes"
        )
    return record
