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


@dataclass(frozen=True)
class ReferenceRecord:
    citekey: str
    entry_type: str
    title: str | None
    authors: tuple[str, ...]
    year: str | None
    doi: str | None = None
    isbn: str | None = None
    url: str | None = None
    eprint: str | None = None

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        if not self.entry_type:
            raise ValueError("entry_type must be non-empty")
        normalized = normalize_doi(self.doi)
        if normalized != self.doi:
            raise ValueError("doi must be normalized")


@dataclass(frozen=True)
class ReferenceAlias:
    alias: str
    canonical_citekey: str
    rationale: str

    def __post_init__(self) -> None:
        validate_citekey(self.alias, field="reference alias")
        validate_citekey(
            self.canonical_citekey,
            field="canonical citekey",
        )
        if not self.rationale:
            raise ValueError("reference alias must be fully explained")


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
    citekey: str
    sha256: str
    byte_size: int
    root_alias: str
    relative_path: str
    rights_status: str
    asset_status: str

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("source-asset hash must be a SHA-256 digest")
        if self.byte_size < 0:
            raise ValueError("source-asset byte size must be non-negative")


@dataclass(frozen=True)
class BibliographyOccurrence:
    citekey: str
    source_id: str
    source_revision: str | None
    source_path: str

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        if not self.source_id or not self.source_path:
            raise ValueError("bibliography source identity must be complete")


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
