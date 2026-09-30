from __future__ import annotations

import hashlib
import json
import re
import warnings
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import validate_citekey

CITATION_DRAFT_SCHEMA_VERSION = 1
CITATION_DRAFT_AUTHORITY = "proposed-noncanonical"
CITATION_DRAFT_MAX_BYTES = 262_144
CITATION_DRAFT_PARSE_CONTRACT_ID = (
    "projectkoios.references.citation-draft-parse@0.1.0"
)
CITATION_DRAFT_PARSER_NAME = "projectkoios-references-citation-draft-parser"
CITATION_DRAFT_PARSER_VERSION = "0.1.0"
CITATION_DRAFT_RENDER_CONTRACT_ID = (
    "projectkoios.references.citation-draft-render@0.1.0"
)
CITATION_DRAFT_RENDERER_NAME = "projectkoios-references-citation-draft-renderer"
CITATION_DRAFT_RENDERER_VERSION = "0.1.0"

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


@dataclass(frozen=True, slots=True)
class CitationDraftEntry(DataObjectModel):
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
        self._validate_text(self.title, "title")
        if not self.personal_authors and not self.corporate_authors:
            raise CitationDraftError("citation draft requires an author")
        if len(self.personal_authors) + len(self.corporate_authors) > 32:
            raise CitationDraftError("citation draft has too many authors")
        for author in (*self.personal_authors, *self.corporate_authors):
            self._validate_text(author, "author", maximum=200)
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
                self._validate_text(value, name)
        if normalize_doi(self.doi) != self.doi:
            raise CitationDraftError("doi must be normalized")
        if self.url is not None:
            self._validate_https_url(self.url)
        if self.urldate is not None and not _DATE.fullmatch(self.urldate):
            raise CitationDraftError("urldate must be YYYY-MM-DD")
        if self.entry_type == "techreport" and self.institution is None:
            raise CitationDraftError("techreport requires institution")

    @property
    def entry_id(self) -> str:
        """Return the deterministic identity of this proposed entry."""
        canonical = json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-draft-entry:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )

    @staticmethod
    def _validate_text(
        value: object,
        name: str,
        *,
        maximum: int = 4096,
    ) -> str:
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise CitationDraftError(f"{name} must be bounded non-empty text")
        if any(ord(character) < 0x20 for character in value):
            raise CitationDraftError(f"{name} contains a control character")
        if any(character in value for character in "{}\\"):
            raise CitationDraftError(f"{name} contains unsafe BibTeX syntax")
        return value

    @staticmethod
    def _validate_https_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            raise CitationDraftError("url must be an unauthenticated HTTPS URL")

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


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDraftParseRequest(DataObjectActionRequest):
    """Request parsing of one bounded citation-draft document."""

    content: bytes
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.content, bytes)
            or len(self.content) > CITATION_DRAFT_MAX_BYTES
        ):
            raise CitationDraftError("citation draft exceeds the byte limit")
        object.__setattr__(
            self,
            "request_id",
            self.identity_for(content=self.content),
        )

    @staticmethod
    def identity_for(*, content: bytes) -> str:
        payload = {
            "contract_id": CITATION_DRAFT_PARSE_CONTRACT_ID,
            "content_byte_size": len(content),
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }
        canonical = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-draft-parse-request:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDraftParseResult(DataObjectActionResult):
    """Bind one parse request to its immutable proposed entries."""

    request: CitationDraftParseRequest
    entries: tuple[CitationDraftEntry, ...]
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CitationDraftParseRequest:
            raise TypeError("request must be a CitationDraftParseRequest")
        if not isinstance(self.entries, tuple) or any(
            not isinstance(entry, CitationDraftEntry) for entry in self.entries
        ):
            raise TypeError("entries must be a CitationDraftEntry tuple")
        if not self.entries:
            raise CitationDraftError("parsed entries must be non-empty")
        object.__setattr__(
            self,
            "result_id",
            self.identity_for(request=self.request, entries=self.entries),
        )

    @staticmethod
    def identity_for(
        *,
        request: CitationDraftParseRequest,
        entries: tuple[CitationDraftEntry, ...],
    ) -> str:
        payload = {
            "contract_id": CITATION_DRAFT_PARSE_CONTRACT_ID,
            "entry_ids": [entry.entry_id for entry in entries],
            "parser_name": CITATION_DRAFT_PARSER_NAME,
            "parser_version": CITATION_DRAFT_PARSER_VERSION,
            "request_id": request.request_id,
        }
        canonical = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-draft-parse-result:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


class CitationDraftParser(
    DataObjectActionizer[CitationDraftParseRequest, CitationDraftParseResult]
):
    """Parse bounded citation-draft documents without granting authority."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CitationDraftParseRequest,
    ) -> CitationDraftParseResult:
        """Return the result of the requested citation-draft parse."""
        return self.parse(request=request)

    def parse(
        self,
        *,
        request: CitationDraftParseRequest,
    ) -> CitationDraftParseResult:
        """Parse one bounded, closed citation-draft document."""
        if type(request) is not CitationDraftParseRequest:
            raise TypeError("request must be a CitationDraftParseRequest")
        try:
            value = json.loads(
                request.content.decode("utf-8", errors="strict"),
                object_pairs_hook=self._without_duplicates,
                parse_constant=self._reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise CitationDraftError(
                "citation draft is malformed JSON"
            ) from error
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
        entries = tuple(
            CitationDraftEntry.from_dict(item) for item in raw_entries
        )
        keys = tuple(item.proposed_citekey for item in entries)
        if len(keys) != len(set(keys)):
            raise CitationDraftError(
                "citation draft contains duplicate citekeys"
            )
        return CitationDraftParseResult(request=request, entries=entries)

    @staticmethod
    def _without_duplicates(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CitationDraftError(f"duplicate JSON member: {key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise CitationDraftError(f"unsupported JSON constant: {value}")


def parse_citation_drafts(content: bytes) -> tuple[CitationDraftEntry, ...]:
    """Deprecated compatibility entry point for citation-draft parsing."""
    warnings.warn(
        "parse_citation_drafts is deprecated; use CitationDraftParser",
        DeprecationWarning,
        stacklevel=2,
    )
    request = CitationDraftParseRequest(content=content)
    return CitationDraftParser().parse(request=request).entries


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDraftRenderRequest(DataObjectActionRequest):
    """Request deterministic BibTeX rendering of proposed entries."""

    entries: tuple[CitationDraftEntry, ...]
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or any(
            not isinstance(entry, CitationDraftEntry) for entry in self.entries
        ):
            raise TypeError("entries must be a CitationDraftEntry tuple")
        if not self.entries:
            raise CitationDraftError("cannot render an empty bibliography")
        object.__setattr__(
            self,
            "request_id",
            self.identity_for(entries=self.entries),
        )

    @staticmethod
    def identity_for(*, entries: tuple[CitationDraftEntry, ...]) -> str:
        payload = {
            "contract_id": CITATION_DRAFT_RENDER_CONTRACT_ID,
            "entry_ids": [entry.entry_id for entry in entries],
        }
        canonical = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-draft-render-request:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDraftRenderResult(DataObjectActionResult):
    """Bind one render request to deterministic UTF-8 BibTeX bytes."""

    request: CitationDraftRenderRequest
    bibliography: bytes
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CitationDraftRenderRequest:
            raise TypeError("request must be a CitationDraftRenderRequest")
        if not isinstance(self.bibliography, bytes):
            raise TypeError("bibliography must be bytes")
        if not self.bibliography:
            raise CitationDraftError("rendered bibliography must be non-empty")
        if len(self.bibliography) > CITATION_DRAFT_MAX_BYTES:
            raise CitationDraftError(
                "rendered bibliography exceeds the byte limit"
            )
        object.__setattr__(
            self,
            "result_id",
            self.identity_for(
                request=self.request,
                bibliography=self.bibliography,
            ),
        )

    @staticmethod
    def identity_for(
        *,
        request: CitationDraftRenderRequest,
        bibliography: bytes,
    ) -> str:
        payload = {
            "bibliography_byte_size": len(bibliography),
            "bibliography_sha256": hashlib.sha256(bibliography).hexdigest(),
            "contract_id": CITATION_DRAFT_RENDER_CONTRACT_ID,
            "renderer_name": CITATION_DRAFT_RENDERER_NAME,
            "renderer_version": CITATION_DRAFT_RENDERER_VERSION,
            "request_id": request.request_id,
        }
        canonical = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-draft-render-result:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


class CitationDraftRenderer(
    DataObjectActionizer[CitationDraftRenderRequest, CitationDraftRenderResult]
):
    """Render proposed citation entries without promoting their authority."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CitationDraftRenderRequest,
    ) -> CitationDraftRenderResult:
        """Return the result of the requested citation-draft render."""
        return self.render(request=request)

    def render(
        self,
        *,
        request: CitationDraftRenderRequest,
    ) -> CitationDraftRenderResult:
        """Render deterministic UTF-8 BibTeX candidate entries."""
        if type(request) is not CitationDraftRenderRequest:
            raise TypeError("request must be a CitationDraftRenderRequest")
        rendered = (
            "\n\n".join(self._render_entry(entry) for entry in request.entries)
            + "\n"
        )
        return CitationDraftRenderResult(
            request=request,
            bibliography=rendered.encode("utf-8"),
        )

    @classmethod
    def _render_entry(cls, entry: CitationDraftEntry) -> str:
        authors = [*cls._escaped_authors(entry.personal_authors)]
        authors.extend(
            f"{{{cls._escape(item)}}}" for item in entry.corporate_authors
        )
        fields: list[tuple[str, str]] = [
            ("author", " and ".join(authors)),
            ("title", f"{{{cls._escape(entry.title)}}}"),
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
        fields.extend(
            (name, cls._escape(value)) for name, value in optional if value
        )
        lines = [f"@{entry.entry_type}{{{entry.proposed_citekey},"]
        lines.extend(f"  {name} = {{{value}}}," for name, value in fields)
        lines[-1] = lines[-1][:-1]
        lines.append("}")
        return "\n".join(lines)

    @classmethod
    def _escaped_authors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(cls._escape(value) for value in values)

    @staticmethod
    def _escape(value: str) -> str:
        CitationDraftEntry._validate_text(value, "BibTeX value")
        return (
            value.replace("&", r"\&")
            .replace("%", r"\%")
            .replace("#", r"\#")
            .replace("_", r"\_")
        )


def render_bibtex(entries: tuple[CitationDraftEntry, ...]) -> bytes:
    """Deprecated compatibility entry point for citation-draft rendering."""
    warnings.warn(
        "render_bibtex is deprecated; use CitationDraftRenderer",
        DeprecationWarning,
        stacklevel=2,
    )
    request = CitationDraftRenderRequest(entries=entries)
    return CitationDraftRenderer().render(request=request).bibliography
