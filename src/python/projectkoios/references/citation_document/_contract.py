from __future__ import annotations

import hashlib
import json
import re
from typing import Any

CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID = (
    "projectkoios.references.citation-source-document-link"
)
CITATION_DOCUMENT_PROJECTION_CONTRACT_ID = (
    "projectkoios.references.citation-document-projection"
)
CITATION_SOURCE_DOCUMENT_LINKER_NAME = (
    "projectkoios-references-citation-source-document-linker"
)
CITATION_DOCUMENT_PROJECTOR_NAME = (
    "projectkoios-references-citation-document-projector"
)

CITATION_DOCUMENT_MAX_OCCURRENCES = 10_000
CITATION_DOCUMENT_MAX_KEYS = 10_000
CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES = 10_000
CITATION_DOCUMENT_MAX_SOURCE_GAPS = 10_000
CITATION_DOCUMENT_MAX_TARGET_RECORDS = 10_000
CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES = 10_000
CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS = 10_000
CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD = 256
CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY = 256
CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY = 256
CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY = 256
CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS = 10_000
CITATION_DOCUMENT_MAX_LINKS = 20_000
CITATION_DOCUMENT_MAX_ID_BYTES = 512
CITATION_DOCUMENT_MAX_TEXT_BYTES = 4_096
CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES = 20_000_000
CITATION_DOCUMENT_MAX_PDF_BYTES = 100_000_000
CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES = 100_000_000
CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES = 100_000_000


def stable_id(prefix: str, payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(canonical) > CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES:
        raise ValueError("canonical identity payload exceeds the byte limit")
    return f"{prefix}:sha256:{hashlib.sha256(canonical).hexdigest()}"


class _CitationDocumentContract:
    _DIGEST = re.compile(r"^[0-9a-f]{64}$")
    _TARGET_IDS = {
        "snapshot": re.compile(r"^citation-snapshot:[0-9a-f]{64}$"),
        "occurrence": re.compile(r"^citation-occurrence:[0-9a-f]{64}$"),
        "group": re.compile(r"^citation-group:[0-9a-f]{64}$"),
        "entry": re.compile(r"^citation-entry:[0-9a-f]{64}$"),
        "gap": re.compile(r"^citation-gap:[0-9a-f]{64}$"),
    }
    _CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")

    @classmethod
    def bounded_text(
        cls,
        value: object,
        *,
        field_name: str,
        maximum: int = CITATION_DOCUMENT_MAX_TEXT_BYTES,
    ) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} must be bounded non-empty text")
        if len(value) > maximum:
            raise ValueError(f"{field_name} exceeds the text limit")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{field_name} must be UTF-8 encodable") from error
        if (
            len(encoded) > maximum
            or value != value.strip()
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in value
            )
        ):
            raise ValueError(f"{field_name} is malformed")
        return value

    @classmethod
    def opaque_id(cls, value: object, *, field_name: str) -> str:
        return cls.bounded_text(
            value,
            field_name=field_name,
            maximum=CITATION_DOCUMENT_MAX_ID_BYTES,
        )

    @classmethod
    def target_id(
        cls,
        value: object,
        *,
        kind: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str) or not cls._TARGET_IDS[kind].fullmatch(
            value
        ):
            raise ValueError(f"{field_name} is invalid")
        return value

    @classmethod
    def content_id(cls, value: object, *, field_name: str) -> str:
        if not isinstance(value, str) or not cls._CONTENT_ID.fullmatch(value):
            raise ValueError(f"{field_name} is invalid")
        return value

    @staticmethod
    def sequential_indexes(
        values: tuple[Any, ...],
        *,
        attribute: str,
        field_name: str,
    ) -> None:
        if tuple(getattr(item, attribute) for item in values) != tuple(
            range(len(values))
        ):
            raise ValueError(f"{field_name} indexes are not canonical")

    @classmethod
    def validate_identity(
        cls,
        *,
        actual: str,
        prefix: str,
        payload: dict[str, object],
        field_name: str,
    ) -> None:
        if actual != stable_id(prefix, payload):
            raise ValueError(f"{field_name} does not match content")
