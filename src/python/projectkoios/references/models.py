from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from projectkoios.references.path_safety import (
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)


def normalize_doi(value: str | None) -> str | None:
    """Normalize a DOI without asserting that it resolves."""
    if value is None:
        return None
    normalized = _DOI_PREFIX.sub("", value.strip()).lower()
    return normalized or None


class ReviewStatus(StrEnum):
    DISCOVERED = "discovered"
    METADATA_VERIFIED = "metadata-verified"
    ABSTRACT_SCREENED = "abstract-screened"
    FULL_TEXT_LOCATED = "full-text-located"
    TRANSCRIBED = "transcribed"
    READ = "read"
    CLAIM_SUPPORT_CHECKED = "claim-support-checked"
    HUMAN_ACCEPTED = "human-accepted"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class ReviewMembership:
    collection_id: str
    citekey: str
    status: ReviewStatus
    decision_note: str | None = None

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        if not self.collection_id:
            raise ValueError("review collection identity must be non-empty")


@dataclass(frozen=True)
class SourceAssetRecord:
    candidate_id: str
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    sha256: str
    byte_size: int
    root_alias: str
    relative_path: str
    rights_status: str
    asset_status: str

    def __post_init__(self) -> None:
        if (
            re.fullmatch(
                r"reference-candidate:sha256:[0-9a-f]{64}",
                self.candidate_id,
            )
            is None
        ):
            raise ValueError("source-asset candidate identity is invalid")
        validate_citekey(
            self.proposed_citekey,
            field="proposed citekey",
        )
        if self.identity_status != "unaccepted-candidate":
            raise ValueError("source asset cannot claim accepted identity")
        if self.citekey_status != "proposed-noncanonical":
            raise ValueError("source-asset citekey must be noncanonical")
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("source-asset hash must be a SHA-256 digest")
        if self.byte_size < 0:
            raise ValueError("source-asset byte size must be non-negative")


@dataclass(frozen=True)
class AbstractRecord:
    citekey: str
    text: str
    provider: str
    source_url: str
    retrieved_at: str
    content_hash: str
    language: str | None = None

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        if not self.text:
            raise ValueError("abstract text must be non-empty")
        if len(self.content_hash) != 64:
            raise ValueError("content_hash must be a SHA-256 digest")


@dataclass(frozen=True)
class CitationCandidate:
    candidate_id: str
    proposed_citekey: str | None
    title: str | None
    authors: str | None
    year: str | None
    doi: str | None
    metadata_status: str
    abstract_status: str
    abstract: str | None = None

    def __post_init__(self) -> None:
        if self.proposed_citekey is not None:
            validate_citekey(
                self.proposed_citekey,
                field="proposed citekey",
            )


@dataclass(frozen=True)
class CitationEdge:
    source_id: str
    target_id: str
    relation: str
    source_locator: str
    verification_status: str
