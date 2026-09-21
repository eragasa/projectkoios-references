from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import validate_citekey

CITATION_DRAFT_SCHEMA_VERSION = 1
CITATION_DRAFT_AUTHORITY = "proposed-noncanonical"
CITATION_DRAFT_MAX_BYTES = 262_144

_ENTRY_TYPES = frozenset({"book", "manual", "misc", "techreport"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_YEAR = re.compile(r"^[0-9]{4}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_FIELDS = {
    "authority",
    "proposed_citekey",
    "entry_type",
    "title",
    "personal_authors",
    "corporate_authors",
    "year",
    "institution",
    "publisher",
    "report_type",
    "number",
    "edition",
    "version_note",
    "doi",
    "url",
    "urldate",
    "source_sha256",
    "source_byte_size",
}


class CitationDraftError(ValueError):
    """Raised when a noncanonical citation draft is unsafe or malformed."""


@dataclass(frozen=True)
class CitationDraftEntry:
    proposed_citekey: str
    entry_type: str
    title: str
    personal_authors: tuple[str, ...]
    corporate_authors: tuple[str, ...]
    year: str
    source_sha256: str
    source_byte_size: int
    institution: str | None = None
    publisher: str | None = None
    report_type: str | None = None
    number: str | None = None
    edition: str | None = None
    version_note: str | None = None
    doi: str | None = None
    url: str | None = None
    urldate: str | None = None
    authority: str = CITATION_DRAFT_AUTHORITY

    def __post_init__(self) -> None:
        validate_citekey(self.proposed_citekey, field="proposed_citekey")
        if self.authority != CITATION_DRAFT_AUTHORITY:
            raise CitationDraftError(
                "citation draft exceeds candidate authority"
            )
        if self.entry_type not in _ENTRY_TYPES:
            raise CitationDraftError("unsupported citation entry type")
        _text(self.title, "title")
        if not self.personal_authors and not self.corporate_authors:
            raise CitationDraftError("citation draft requires an author")
        if len(self.personal_authors) + len(self.corporate_authors) > 32:
            raise CitationDraftError("citation draft has too many authors")
        for author in (*self.personal_authors, *self.corporate_authors):
            _text(author, "author", maximum=200)
        if not _YEAR.fullmatch(self.year):
            raise CitationDraftError("year must be a four-digit string")
        if not _SHA256.fullmatch(self.source_sha256):
            raise CitationDraftError("source_sha256 must be a SHA-256 digest")
        if type(self.source_byte_size) is not int or self.source_byte_size <= 0:
            raise CitationDraftError("source_byte_size must be positive")
        for name in (
            "institution",
            "publisher",
            "report_type",
            "number",
            "edition",
            "version_note",
        ):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if normalize_doi(self.doi) != self.doi:
            raise CitationDraftError("doi must be normalized")
        if self.url is not None:
            _https_url(self.url)
        if self.urldate is not None and not _DATE.fullmatch(self.urldate):
            raise CitationDraftError("urldate must be YYYY-MM-DD")
        if self.entry_type == "techreport" and self.institution is None:
            raise CitationDraftError("techreport requires institution")

    @classmethod
    def from_dict(cls, value: object) -> CitationDraftEntry:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            unknown = set(value) - _FIELDS if isinstance(value, dict) else set()
            missing = (
                _FIELDS - set(value) if isinstance(value, dict) else _FIELDS
            )
            raise CitationDraftError(
                f"citation entry fields differ: missing={sorted(missing)}, "
                f"unknown={sorted(unknown)}"
            )
        strings = {
            "authority",
            "proposed_citekey",
            "entry_type",
            "title",
            "year",
            "source_sha256",
        }
        if any(not isinstance(value[name], str) for name in strings):
            raise CitationDraftError("required citation fields must be strings")
        optional = {
            "institution",
            "publisher",
            "report_type",
            "number",
            "edition",
            "version_note",
            "doi",
            "url",
            "urldate",
        }
        if any(
            value[name] is not None and not isinstance(value[name], str)
            for name in optional
        ):
            raise CitationDraftError("optional citation fields are invalid")
        authors = []
        for name in ("personal_authors", "corporate_authors"):
            raw = value[name]
            if not isinstance(raw, list) or any(
                not isinstance(item, str) for item in raw
            ):
                raise CitationDraftError(f"{name} must be a string array")
            authors.append(tuple(raw))
        byte_size = value["source_byte_size"]
        if type(byte_size) is not int:
            raise CitationDraftError("source_byte_size must be an integer")
        return cls(
            proposed_citekey=value["proposed_citekey"],
            entry_type=value["entry_type"],
            title=value["title"],
            personal_authors=authors[0],
            corporate_authors=authors[1],
            year=value["year"],
            source_sha256=value["source_sha256"],
            source_byte_size=byte_size,
            institution=value["institution"],
            publisher=value["publisher"],
            report_type=value["report_type"],
            number=value["number"],
            edition=value["edition"],
            version_note=value["version_note"],
            doi=value["doi"],
            url=value["url"],
            urldate=value["urldate"],
            authority=value["authority"],
        )


def parse_citation_drafts(content: bytes) -> tuple[CitationDraftEntry, ...]:
    """Parse one bounded, closed citation-draft document."""
    if (
        not isinstance(content, bytes)
        or len(content) > CITATION_DRAFT_MAX_BYTES
    ):
        raise CitationDraftError("citation draft exceeds the byte limit")
    try:
        value = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise CitationDraftError("citation draft is malformed JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "entries",
    }:
        raise CitationDraftError("citation draft root fields differ")
    if value["schema_version"] != CITATION_DRAFT_SCHEMA_VERSION:
        raise CitationDraftError("unsupported citation-draft schema")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CitationDraftError("citation draft entries must be non-empty")
    if len(raw_entries) > 256:
        raise CitationDraftError("citation draft exceeds the entry limit")
    entries = tuple(CitationDraftEntry.from_dict(item) for item in raw_entries)
    keys = tuple(item.proposed_citekey for item in entries)
    if len(keys) != len(set(keys)):
        raise CitationDraftError("citation draft contains duplicate citekeys")
    return entries


def render_bibtex(entries: tuple[CitationDraftEntry, ...]) -> bytes:
    """Render deterministic UTF-8 BibTeX without promoting candidate keys."""
    if not entries:
        raise CitationDraftError("cannot render an empty bibliography")
    rendered = "\n\n".join(_render_entry(entry) for entry in entries) + "\n"
    content = rendered.encode("utf-8")
    if len(content) > CITATION_DRAFT_MAX_BYTES:
        raise CitationDraftError("rendered bibliography exceeds the byte limit")
    return content


def _render_entry(entry: CitationDraftEntry) -> str:
    authors = [*_escaped_authors(entry.personal_authors)]
    authors.extend(f"{{{_escape(item)}}}" for item in entry.corporate_authors)
    fields: list[tuple[str, str]] = [
        ("author", " and ".join(authors)),
        ("title", f"{{{_escape(entry.title)}}}"),
    ]
    optional = (
        ("institution", entry.institution),
        ("publisher", entry.publisher),
        ("type", entry.report_type),
        ("number", entry.number),
        ("edition", entry.edition),
        ("year", entry.year),
        ("doi", entry.doi),
        ("url", entry.url),
        ("urldate", entry.urldate),
        ("note", entry.version_note),
    )
    fields.extend((name, _escape(value)) for name, value in optional if value)
    lines = [f"@{entry.entry_type}{{{entry.proposed_citekey},"]
    lines.extend(f"  {name} = {{{value}}}," for name, value in fields)
    lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


def _escaped_authors(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_escape(value) for value in values)


def _escape(value: str) -> str:
    _text(value, "BibTeX value")
    return (
        value.replace("&", r"\&")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("_", r"\_")
    )


def _text(value: object, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CitationDraftError(f"{name} must be bounded non-empty text")
    if any(ord(character) < 0x20 for character in value):
        raise CitationDraftError(f"{name} contains a control character")
    if any(character in value for character in "{}\\"):
        raise CitationDraftError(f"{name} contains unsafe BibTeX syntax")
    return value


def _https_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise CitationDraftError("url must be an unauthenticated HTTPS URL")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CitationDraftError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CitationDraftError(f"unsupported JSON constant: {value}")
