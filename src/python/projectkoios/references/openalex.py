from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from projectkoios.references.io_limits import (
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_utf8_size,
    validate_json_text_nesting,
)

OPENALEX_WORKS_ENDPOINT: Final = "https://api.openalex.org/works"
OPENALEX_WORKS_SEARCH_SCHEMA_VERSION: Final = 1
OPENALEX_WORKS_PARSER_VERSION: Final = "openalex-works-search-v1"
OPENALEX_PROVIDER_NAME: Final = "openalex"
OPENALEX_MAX_QUERY_CHARACTERS: Final = 500
OPENALEX_MAX_PAGE: Final = 10_000
OPENALEX_MAX_PER_PAGE: Final = 100
OPENALEX_MAX_BASIC_PAGE_RESULTS: Final = 10_000
OPENALEX_MAX_AUTHORS_PER_WORK: Final = 1_024
OPENALEX_MAX_TIMEOUT_SECONDS: Final = 60.0
OPENALEX_MAX_RESPONSE_BYTES: Final = 2_000_000
OPENALEX_MAX_COUNT: Final = 1_000_000_000
OPENALEX_MAX_COST_USD: Final = Decimal("1000000")
OPENALEX_MAX_COST_DECIMAL_PLACES: Final = 8
OPENALEX_MAX_COST_FIXED_CHARACTERS: Final = 16
OPENALEX_WORKS_SEARCH_IO_LIMITS: Final = ReferenceIOLimits(
    profile="openalex-works-search-v1",
    max_response_bytes=OPENALEX_MAX_RESPONSE_BYTES,
    max_json_bytes=OPENALEX_MAX_RESPONSE_BYTES,
    max_json_depth=16,
    max_text_bytes=512_000,
    max_candidates=OPENALEX_MAX_PER_PAGE,
    max_entries=100_000,
)

__all__ = [
    "OPENALEX_MAX_AUTHORS_PER_WORK",
    "OPENALEX_MAX_BASIC_PAGE_RESULTS",
    "OPENALEX_MAX_COUNT",
    "OPENALEX_MAX_COST_DECIMAL_PLACES",
    "OPENALEX_MAX_COST_FIXED_CHARACTERS",
    "OPENALEX_MAX_COST_USD",
    "OPENALEX_MAX_PAGE",
    "OPENALEX_MAX_PER_PAGE",
    "OPENALEX_MAX_QUERY_CHARACTERS",
    "OPENALEX_MAX_RESPONSE_BYTES",
    "OPENALEX_MAX_TIMEOUT_SECONDS",
    "OPENALEX_PROVIDER_NAME",
    "OPENALEX_WORKS_ENDPOINT",
    "OPENALEX_WORKS_PARSER_VERSION",
    "OPENALEX_WORKS_SEARCH_IO_LIMITS",
    "OPENALEX_WORKS_SEARCH_SCHEMA_VERSION",
    "HttpsOpenAlexWorksTransport",
    "OpenAlexError",
    "OpenAlexProjectionError",
    "OpenAlexRateLimitError",
    "OpenAlexTransportRequest",
    "OpenAlexTransportResponse",
    "OpenAlexUnavailableError",
    "OpenAlexUpstreamError",
    "OpenAlexWorkObservation",
    "OpenAlexWorksClient",
    "OpenAlexWorksProvider",
    "OpenAlexWorksSearchProvenance",
    "OpenAlexWorksSearchRequest",
    "OpenAlexWorksSearchRequestError",
    "OpenAlexWorksSearchResult",
    "OpenAlexWorksTransport",
    "create_openalex_works_provider",
]

_OPENALEX_SELECT_FIELDS: Final = (
    "id",
    "title",
    "publication_year",
    "type",
    "doi",
    "authorships",
    "primary_location",
    "cited_by_count",
)
_OPENALEX_WORK_ID = re.compile(r"https://openalex\.org/W[1-9][0-9]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_COMPONENT = re.compile(r"[a-z][a-z0-9._+-]{0,127}")
_MAX_API_KEY_CHARACTERS = 4_096
_MAX_USER_AGENT_BYTES = 512
_MAX_CONTENT_ENCODING_BYTES = 128
_MAX_SOURCE_URL_BYTES = 16_384
_MAX_TITLE_BYTES = 65_536
_MAX_WORK_TYPE_BYTES = 256
_MAX_DOI_BYTES = 4_096
_MAX_AUTHOR_BYTES = 16_384
_MAX_AUTHORS_BYTES = 512_000
_MAX_SOURCE_NAME_BYTES = 16_384
_MAX_LANDING_URL_BYTES = 16_384
_MAX_JSON_LIST_ITEMS = 4_096
_MAX_JSON_OBJECT_FIELDS = 256
_MAX_DECIMAL_CHARACTERS = 64


class OpenAlexError(ValueError):
    """Base error for bounded OpenAlex works search."""


class OpenAlexWorksSearchRequestError(OpenAlexError):
    """Raised when a caller supplies an invalid bounded search request."""


class OpenAlexProjectionError(OpenAlexError):
    """Raised when upstream bytes cannot form the immutable owner result."""


class OpenAlexUnavailableError(OpenAlexError):
    """Raised when the OpenAlex transport cannot complete one request."""


class OpenAlexUpstreamError(OpenAlexError):
    """Raised when OpenAlex returns a non-success HTTP status."""

    def __init__(self, status_code: int) -> None:
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ValueError("upstream status code is invalid")
        self.status_code = status_code
        super().__init__(f"OpenAlex upstream returned HTTP {status_code}")


class OpenAlexRateLimitError(OpenAlexUpstreamError):
    """Raised when OpenAlex refuses the request because of a rate limit."""

    def __init__(
        self,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        if retry_after_seconds is not None and (
            type(retry_after_seconds) is not int
            or not 0 <= retry_after_seconds <= 86_400
        ):
            raise ValueError("retry-after seconds are invalid")
        self.retry_after_seconds = retry_after_seconds
        super().__init__(429)


@dataclass(frozen=True)
class OpenAlexWorksSearchRequest:
    """One normalized, bounded basic-page works search."""

    query: str
    page: int = 1
    per_page: int = 25

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise OpenAlexWorksSearchRequestError("query must be text")
        if _contains_control_text(self.query):
            raise OpenAlexWorksSearchRequestError(
                "query contains control characters"
            )
        query = self.query.strip()
        if not query:
            raise OpenAlexWorksSearchRequestError("query must be non-empty")
        if len(query) > OPENALEX_MAX_QUERY_CHARACTERS:
            raise OpenAlexWorksSearchRequestError(
                "query exceeds the 500-character limit"
            )
        try:
            query.encode("utf-8")
        except UnicodeEncodeError as error:
            raise OpenAlexWorksSearchRequestError(
                "query is not valid Unicode text"
            ) from error
        if (
            type(self.page) is not int
            or not 1 <= self.page <= OPENALEX_MAX_PAGE
        ):
            raise OpenAlexWorksSearchRequestError(
                "page must be an integer from 1 through 10000"
            )
        if (
            type(self.per_page) is not int
            or not 1 <= self.per_page <= OPENALEX_MAX_PER_PAGE
        ):
            raise OpenAlexWorksSearchRequestError(
                "per_page must be an integer from 1 through 100"
            )
        if self.page * self.per_page > OPENALEX_MAX_BASIC_PAGE_RESULTS:
            raise OpenAlexWorksSearchRequestError(
                "page and per_page exceed the 10000-result basic-page limit"
            )
        object.__setattr__(self, "query", query)


@dataclass(frozen=True)
class OpenAlexWorkObservation:
    """Selected OpenAlex work fields retained as untrusted provider data."""

    work_id: str
    title: str
    publication_year: int | None
    work_type: str
    doi: str | None
    authors: tuple[str, ...]
    primary_source_display_name: str | None
    cited_by_count: int
    landing_url: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.work_id, str)
            or _OPENALEX_WORK_ID.fullmatch(self.work_id) is None
        ):
            raise OpenAlexProjectionError("OpenAlex work ID is invalid")
        _provider_text(
            self.title,
            field="title",
            maximum_bytes=_MAX_TITLE_BYTES,
            allow_empty=False,
        )
        if self.publication_year is not None and (
            type(self.publication_year) is not int
            or not 0 <= self.publication_year <= 9_999
        ):
            raise OpenAlexProjectionError("publication year is invalid")
        _provider_text(
            self.work_type,
            field="work type",
            maximum_bytes=_MAX_WORK_TYPE_BYTES,
            allow_empty=False,
        )
        if self.doi is not None:
            _provider_text(
                self.doi,
                field="DOI",
                maximum_bytes=_MAX_DOI_BYTES,
                allow_empty=False,
            )
        if not isinstance(self.authors, tuple):
            raise OpenAlexProjectionError("authors must be an immutable tuple")
        if len(self.authors) > OPENALEX_MAX_AUTHORS_PER_WORK:
            raise OpenAlexProjectionError("author list exceeds its item limit")
        author_bytes = 0
        for author in self.authors:
            author_bytes += _provider_text(
                author,
                field="author display name",
                maximum_bytes=_MAX_AUTHOR_BYTES,
                allow_empty=False,
            )
        if author_bytes > _MAX_AUTHORS_BYTES:
            raise OpenAlexProjectionError("author list exceeds its byte limit")
        if self.primary_source_display_name is not None:
            _provider_text(
                self.primary_source_display_name,
                field="primary source display name",
                maximum_bytes=_MAX_SOURCE_NAME_BYTES,
                allow_empty=False,
            )
        if (
            type(self.cited_by_count) is not int
            or not 0 <= self.cited_by_count <= OPENALEX_MAX_COUNT
        ):
            raise OpenAlexProjectionError("cited-by count is invalid")
        _validate_http_url(
            self.landing_url,
            field="landing URL",
            maximum_bytes=_MAX_LANDING_URL_BYTES,
        )


@dataclass(frozen=True)
class OpenAlexWorksSearchProvenance:
    """Credential-free retrieval evidence for exact OpenAlex response bytes."""

    schema_version: int
    provider: str
    request: OpenAlexWorksSearchRequest
    retrieved_at: str
    source_url: str
    response_sha256: str
    response_bytes: int
    parser_version: str
    max_response_bytes: int
    effective_limits: ReferenceIOLimits
    effective_limits_id: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != OPENALEX_WORKS_SEARCH_SCHEMA_VERSION
        ):
            raise OpenAlexProjectionError(
                "OpenAlex provenance schema version is incompatible"
            )
        if self.provider != OPENALEX_PROVIDER_NAME:
            raise OpenAlexProjectionError(
                "OpenAlex provider identity conflicts"
            )
        if not isinstance(self.request, OpenAlexWorksSearchRequest):
            raise OpenAlexProjectionError(
                "OpenAlex request evidence is invalid"
            )
        _parse_timestamp(self.retrieved_at)
        if self.source_url != _works_search_url(self.request):
            raise OpenAlexProjectionError("OpenAlex source URL conflicts")
        _validate_source_url(self.source_url)
        if (
            not isinstance(self.response_sha256, str)
            or _SHA256.fullmatch(self.response_sha256) is None
        ):
            raise OpenAlexProjectionError("response hash is invalid")
        if (
            type(self.response_bytes) is not int
            or not 0 <= self.response_bytes <= OPENALEX_MAX_RESPONSE_BYTES
        ):
            raise OpenAlexProjectionError("response byte size is invalid")
        if self.parser_version != OPENALEX_WORKS_PARSER_VERSION:
            raise OpenAlexProjectionError("OpenAlex parser version conflicts")
        if (
            type(self.max_response_bytes) is not int
            or not 0 < self.max_response_bytes <= OPENALEX_MAX_RESPONSE_BYTES
            or self.response_bytes > self.max_response_bytes
        ):
            raise OpenAlexProjectionError("response byte limit is invalid")
        if not isinstance(self.effective_limits, ReferenceIOLimits):
            raise OpenAlexProjectionError("effective I/O limits are invalid")
        if (
            self.effective_limits.profile
            != OPENALEX_WORKS_SEARCH_IO_LIMITS.profile
            or self.effective_limits.max_response_bytes
            != self.max_response_bytes
            or self.effective_limits_id != self.effective_limits.evidence_id
        ):
            raise OpenAlexProjectionError(
                "effective I/O-limit evidence conflicts"
            )

    @property
    def observation_id(self) -> str:
        rendered = json.dumps(
            {
                "schema_version": self.schema_version,
                "provider": self.provider,
                "request": asdict(self.request),
                "retrieved_at": self.retrieved_at,
                "source_url": self.source_url,
                "response_sha256": self.response_sha256,
                "response_bytes": self.response_bytes,
                "parser_version": self.parser_version,
                "max_response_bytes": self.max_response_bytes,
                "effective_limits": self.effective_limits.to_dict(),
                "effective_limits_id": self.effective_limits_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return (
            "openalex-works-search:sha256:"
            + hashlib.sha256(rendered).hexdigest()
        )


@dataclass(frozen=True)
class OpenAlexWorksSearchResult:
    """One immutable, non-authoritative OpenAlex works-search observation."""

    total_count: int
    page: int
    per_page: int
    cost_usd: Decimal | None
    works: tuple[OpenAlexWorkObservation, ...]
    provenance: OpenAlexWorksSearchProvenance

    def __post_init__(self) -> None:
        if (
            type(self.total_count) is not int
            or not 0 <= self.total_count <= OPENALEX_MAX_COUNT
        ):
            raise OpenAlexProjectionError("total count is invalid")
        if not isinstance(self.provenance, OpenAlexWorksSearchProvenance):
            raise OpenAlexProjectionError("search provenance is invalid")
        if (
            self.page != self.provenance.request.page
            or self.per_page != self.provenance.request.per_page
        ):
            raise OpenAlexProjectionError(
                "result paging conflicts with request"
            )
        if not isinstance(self.works, tuple):
            raise OpenAlexProjectionError("works must be an immutable tuple")
        if len(self.works) > self.per_page:
            raise OpenAlexProjectionError(
                "work list exceeds requested page size"
            )
        if len(self.works) > self.total_count:
            raise OpenAlexProjectionError("work list exceeds total count")
        if any(
            not isinstance(item, OpenAlexWorkObservation) for item in self.works
        ):
            raise OpenAlexProjectionError("work observation is invalid")
        _validate_cost(self.cost_usd)


class OpenAlexTransportRequest:
    """Bounded transport input with a representation-hidden credential."""

    __slots__ = (
        "url",
        "timeout_seconds",
        "max_response_bytes",
        "effective_limits",
        "user_agent",
        "__api_key",
    )

    def __init__(
        self,
        *,
        url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        effective_limits: ReferenceIOLimits,
        user_agent: str,
        api_key: str | None,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.effective_limits = effective_limits
        self.user_agent = user_agent
        self.__api_key = api_key

    @property
    def has_api_key(self) -> bool:
        return self.__api_key is not None

    def _headers_for_transport(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": self.user_agent,
        }
        if self.__api_key is not None:
            headers["Authorization"] = f"Bearer {self.__api_key}"
        return headers

    def __repr__(self) -> str:
        return (
            "OpenAlexTransportRequest("
            f"url={self.url!r}, timeout_seconds={self.timeout_seconds!r}, "
            f"max_response_bytes={self.max_response_bytes!r}, "
            f"effective_limits={self.effective_limits!r}, "
            f"user_agent={self.user_agent!r}, "
            f"has_api_key={self.has_api_key!r})"
        )


@dataclass(frozen=True)
class OpenAlexTransportResponse:
    """Raw bounded transport response used by the OpenAlex owner adapter."""

    status_code: int
    body: bytes
    retrieved_at: str
    retry_after_seconds: int | None = None
    content_encoding: str | None = None


class OpenAlexWorksTransport(Protocol):
    def get(
        self, request: OpenAlexTransportRequest
    ) -> OpenAlexTransportResponse:
        """Return one bounded OpenAlex transport observation."""


@runtime_checkable
class OpenAlexWorksProvider(Protocol):
    def search_works(
        self,
        request: OpenAlexWorksSearchRequest,
    ) -> OpenAlexWorksSearchResult:
        """Return one read-only, non-authoritative works-search observation."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class HttpsOpenAlexWorksTransport:
    """Fixed-origin HTTPS transport; tests inject a deterministic fake."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._opener = build_opener(_NoRedirectHandler())

    def get(
        self, request: OpenAlexTransportRequest
    ) -> OpenAlexTransportResponse:
        if not isinstance(request, OpenAlexTransportRequest):
            raise OpenAlexProjectionError(
                "OpenAlex transport request type is invalid"
            )
        _validate_source_url(request.url)
        http_request = Request(
            request.url,
            headers=request._headers_for_transport(),
            method="GET",
        )
        try:
            with self._opener.open(
                http_request,
                timeout=request.timeout_seconds,
            ) as response:
                body = _read_bounded_body(response, request)
                status_code = response.getcode()
                content_encoding = response.headers.get("Content-Encoding")
                retry_after = response.headers.get("Retry-After")
        except HTTPError as error:
            try:
                body = _read_bounded_body(error, request)
                content_encoding = error.headers.get("Content-Encoding")
                retry_after = error.headers.get("Retry-After")
                status_code = error.code
            finally:
                error.close()
        except TimeoutError, URLError, OSError:
            raise OpenAlexUnavailableError(
                "OpenAlex transport is unavailable"
            ) from None
        retrieved_at = self._clock().isoformat()
        return OpenAlexTransportResponse(
            status_code=status_code,
            body=body,
            retrieved_at=retrieved_at,
            retry_after_seconds=_parse_retry_after(retry_after),
            content_encoding=content_encoding,
        )


class OpenAlexWorksClient:
    """Bounded, read-only OpenAlex works-search provider."""

    __slots__ = (
        "__api_key",
        "timeout_seconds",
        "user_agent",
        "limits",
        "transport",
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        user_agent: str = "projectkoios-references/0.0.0",
        transport: OpenAlexWorksTransport | None = None,
        limits: ReferenceIOLimits = OPENALEX_WORKS_SEARCH_IO_LIMITS,
    ) -> None:
        self.__api_key = _validate_api_key(api_key)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= OPENALEX_MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("OpenAlex timeout must be finite and in (0, 60]")
        self.timeout_seconds = float(timeout_seconds)
        self.user_agent = _validate_user_agent(user_agent)
        if not isinstance(limits, ReferenceIOLimits):
            raise ValueError("OpenAlex I/O limits are invalid")
        if limits.profile != OPENALEX_WORKS_SEARCH_IO_LIMITS.profile:
            raise ValueError("OpenAlex I/O-limit profile is incompatible")
        for name in (
            "max_response_bytes",
            "max_json_bytes",
            "max_json_depth",
            "max_text_bytes",
            "max_candidates",
            "max_entries",
        ):
            if getattr(limits, name) is None:
                raise ValueError(f"OpenAlex I/O limits must define {name}")
        if _required_limit(limits.max_response_bytes, "max_response_bytes") > (
            OPENALEX_MAX_RESPONSE_BYTES
        ):
            raise ValueError("OpenAlex response limit exceeds its hard ceiling")
        self.limits = limits
        self.transport = transport or HttpsOpenAlexWorksTransport()

    def search_works(
        self,
        request: OpenAlexWorksSearchRequest,
    ) -> OpenAlexWorksSearchResult:
        if not isinstance(request, OpenAlexWorksSearchRequest):
            raise OpenAlexWorksSearchRequestError(
                "request must be OpenAlexWorksSearchRequest"
            )
        maximum_results = _required_limit(
            self.limits.max_candidates,
            "max_candidates",
        )
        if request.per_page > maximum_results:
            raise OpenAlexWorksSearchRequestError(
                "per_page exceeds the active OpenAlex result limit"
            )
        source_url = _works_search_url(request)
        maximum_response_bytes = _required_limit(
            self.limits.max_response_bytes,
            "max_response_bytes",
        )
        transport_request = OpenAlexTransportRequest(
            url=source_url,
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=maximum_response_bytes,
            effective_limits=self.limits,
            user_agent=self.user_agent,
            api_key=self.__api_key,
        )
        try:
            response = self.transport.get(transport_request)
        except OpenAlexError:
            raise
        except TimeoutError, OSError, URLError:
            raise OpenAlexUnavailableError(
                "OpenAlex transport is unavailable"
            ) from None
        _validate_transport_response(
            response,
            maximum_response_bytes=maximum_response_bytes,
        )
        if response.status_code == 429:
            raise OpenAlexRateLimitError(
                retry_after_seconds=response.retry_after_seconds
            )
        if response.status_code != 200:
            raise OpenAlexUpstreamError(response.status_code)
        provenance = OpenAlexWorksSearchProvenance(
            schema_version=OPENALEX_WORKS_SEARCH_SCHEMA_VERSION,
            provider=OPENALEX_PROVIDER_NAME,
            request=request,
            retrieved_at=response.retrieved_at,
            source_url=source_url,
            response_sha256=hashlib.sha256(response.body).hexdigest(),
            response_bytes=len(response.body),
            parser_version=OPENALEX_WORKS_PARSER_VERSION,
            max_response_bytes=maximum_response_bytes,
            effective_limits=self.limits,
            effective_limits_id=self.limits.evidence_id,
        )
        return _parse_works_response(response.body, provenance)


def create_openalex_works_provider(
    *,
    api_key: str | None = None,
    timeout_seconds: float = 10.0,
    user_agent: str = "projectkoios-references/0.0.0",
    transport: OpenAlexWorksTransport | None = None,
    limits: ReferenceIOLimits = OPENALEX_WORKS_SEARCH_IO_LIMITS,
) -> OpenAlexWorksProvider:
    """Create the concrete bounded provider behind the stable protocol."""
    return OpenAlexWorksClient(
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        transport=transport,
        limits=limits,
    )


def _validate_transport_response(
    response: object,
    *,
    maximum_response_bytes: int,
) -> None:
    if not isinstance(response, OpenAlexTransportResponse):
        raise OpenAlexProjectionError(
            "OpenAlex transport response type is invalid"
        )
    if type(response.status_code) is not int or not (
        100 <= response.status_code <= 599
    ):
        raise OpenAlexProjectionError("OpenAlex HTTP status is invalid")
    if not isinstance(response.body, bytes):
        raise OpenAlexProjectionError("OpenAlex transport body must be bytes")
    if len(response.body) > maximum_response_bytes:
        raise OpenAlexProjectionError(
            "OpenAlex response exceeds its byte limit"
        )
    _parse_timestamp(response.retrieved_at)
    if response.retry_after_seconds is not None and (
        type(response.retry_after_seconds) is not int
        or not 0 <= response.retry_after_seconds <= 86_400
    ):
        raise OpenAlexProjectionError(
            "OpenAlex retry-after metadata is invalid"
        )
    if response.content_encoding is not None:
        if not isinstance(response.content_encoding, str):
            raise OpenAlexProjectionError(
                "OpenAlex content encoding metadata is invalid"
            )
        try:
            encoding_bytes = bounded_utf8_size(
                response.content_encoding,
                max_bytes=_MAX_CONTENT_ENCODING_BYTES,
            )
        except UnicodeEncodeError as error:
            raise OpenAlexProjectionError(
                "OpenAlex content encoding metadata is invalid"
            ) from error
        if (
            _contains_control_text(response.content_encoding)
            or encoding_bytes > _MAX_CONTENT_ENCODING_BYTES
        ):
            raise OpenAlexProjectionError(
                "OpenAlex content encoding metadata is invalid"
            )
        if response.content_encoding.strip().lower() not in {"", "identity"}:
            raise OpenAlexProjectionError(
                "OpenAlex response uses unsupported content encoding"
            )


def _parse_works_response(
    body: bytes,
    provenance: OpenAlexWorksSearchProvenance,
) -> OpenAlexWorksSearchResult:
    payload = _decode_json_object(body, limits=provenance.effective_limits)
    if set(payload) != {"meta", "results", "group_by"}:
        raise OpenAlexProjectionError(
            "OpenAlex response fields are incomplete or unknown"
        )
    group_by = payload["group_by"]
    if not isinstance(group_by, list) or group_by:
        raise OpenAlexProjectionError(
            "OpenAlex works search must not contain grouped results"
        )
    meta = payload["meta"]
    if not isinstance(meta, dict):
        raise OpenAlexProjectionError("OpenAlex meta must be an object")
    for field in ("count", "page", "per_page"):
        if field not in meta:
            raise OpenAlexProjectionError(
                "OpenAlex meta is missing required paging fields"
            )
    total_count = _bounded_nonnegative_integer(meta["count"], "total count")
    page = _bounded_nonnegative_integer(meta["page"], "page")
    per_page = _bounded_nonnegative_integer(meta["per_page"], "per_page")
    if (
        page != provenance.request.page
        or per_page != provenance.request.per_page
    ):
        raise OpenAlexProjectionError(
            "OpenAlex paging echo conflicts with the request"
        )
    cost = _parse_cost(meta.get("cost_usd"))
    raw_results = payload["results"]
    if not isinstance(raw_results, list):
        raise OpenAlexProjectionError("OpenAlex results must be a list")
    if len(raw_results) > provenance.request.per_page:
        raise OpenAlexProjectionError(
            "OpenAlex results exceed the requested page size"
        )
    works = tuple(_parse_work(item) for item in raw_results)
    return OpenAlexWorksSearchResult(
        total_count=total_count,
        page=page,
        per_page=per_page,
        cost_usd=cost,
        works=works,
        provenance=provenance,
    )


def _parse_work(value: object) -> OpenAlexWorkObservation:
    if not isinstance(value, dict):
        raise OpenAlexProjectionError("OpenAlex work must be an object")
    if set(value) != set(_OPENALEX_SELECT_FIELDS):
        raise OpenAlexProjectionError(
            "OpenAlex selected work fields are incomplete or unknown"
        )
    work_id = _required_provider_text(
        value["id"],
        field="work ID",
        maximum_bytes=_MAX_LANDING_URL_BYTES,
    )
    title = _required_provider_text(
        value["title"],
        field="title",
        maximum_bytes=_MAX_TITLE_BYTES,
    )
    raw_year = value["publication_year"]
    publication_year: int | None
    if raw_year is None:
        publication_year = None
    elif type(raw_year) is int and 0 <= raw_year <= 9_999:
        publication_year = raw_year
    else:
        raise OpenAlexProjectionError("publication year is invalid")
    work_type = _required_provider_text(
        value["type"],
        field="work type",
        maximum_bytes=_MAX_WORK_TYPE_BYTES,
    )
    raw_doi = value["doi"]
    doi = (
        None
        if raw_doi is None
        else _required_provider_text(
            raw_doi,
            field="DOI",
            maximum_bytes=_MAX_DOI_BYTES,
        )
    )
    authors = _parse_authors(value["authorships"])
    primary_source, landing_url = _parse_primary_location(
        value["primary_location"],
        work_id,
    )
    cited_by_count = _bounded_nonnegative_integer(
        value["cited_by_count"],
        "cited-by count",
    )
    return OpenAlexWorkObservation(
        work_id=work_id,
        title=title,
        publication_year=publication_year,
        work_type=work_type,
        doi=doi,
        authors=authors,
        primary_source_display_name=primary_source,
        cited_by_count=cited_by_count,
        landing_url=landing_url,
    )


def _parse_authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise OpenAlexProjectionError("OpenAlex authorships must be a list")
    if len(value) > OPENALEX_MAX_AUTHORS_PER_WORK:
        raise OpenAlexProjectionError("OpenAlex authorships exceed their limit")
    authors: list[str] = []
    for authorship in value:
        if not isinstance(authorship, dict):
            raise OpenAlexProjectionError(
                "OpenAlex authorship must be an object"
            )
        author = authorship.get("author")
        if not isinstance(author, dict):
            raise OpenAlexProjectionError(
                "OpenAlex authorship has no author object"
            )
        authors.append(
            _required_provider_text(
                author.get("display_name"),
                field="author display name",
                maximum_bytes=_MAX_AUTHOR_BYTES,
            )
        )
    return tuple(authors)


def _parse_primary_location(
    value: object,
    work_id: str,
) -> tuple[str | None, str]:
    if value is None:
        return None, work_id
    if not isinstance(value, dict):
        raise OpenAlexProjectionError(
            "OpenAlex primary location must be an object or null"
        )
    raw_source = value.get("source")
    source_name: str | None = None
    if raw_source is not None:
        if not isinstance(raw_source, dict):
            raise OpenAlexProjectionError(
                "OpenAlex primary source must be an object or null"
            )
        raw_name = raw_source.get("display_name")
        if raw_name is not None:
            source_name = _required_provider_text(
                raw_name,
                field="primary source display name",
                maximum_bytes=_MAX_SOURCE_NAME_BYTES,
            )
    raw_landing = value.get("landing_page_url")
    if raw_landing is None:
        return source_name, work_id
    landing_url = _required_provider_text(
        raw_landing,
        field="landing URL",
        maximum_bytes=_MAX_LANDING_URL_BYTES,
    )
    _validate_http_url(
        landing_url,
        field="landing URL",
        maximum_bytes=_MAX_LANDING_URL_BYTES,
    )
    return source_name, landing_url


class _DuplicateJsonKeyError(ValueError):
    pass


class _NonStandardJsonConstantError(ValueError):
    pass


class _JsonNumberError(ValueError):
    pass


def _decode_json_object(
    body: bytes,
    *,
    limits: ReferenceIOLimits,
) -> dict[str, object]:
    maximum_response = _required_limit(
        limits.max_response_bytes,
        "max_response_bytes",
    )
    if len(body) > maximum_response:
        raise OpenAlexProjectionError(
            "OpenAlex response exceeds its byte limit"
        )
    try:
        text = body.decode("utf-8")
        validate_json_text_nesting(
            text,
            limits=limits,
            resource="OpenAlex response",
        )
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
            parse_int=_parse_json_integer,
            parse_float=_parse_json_decimal,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ReferenceIOLimitError,
        _DuplicateJsonKeyError,
        _NonStandardJsonConstantError,
        _JsonNumberError,
    ) as error:
        raise OpenAlexProjectionError(
            "OpenAlex response is not bounded strict UTF-8 JSON"
        ) from error
    _validate_json_structure(value, limits=limits)
    if not isinstance(value, dict):
        raise OpenAlexProjectionError("OpenAlex response must be an object")
    return value


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    if len(pairs) > _MAX_JSON_OBJECT_FIELDS:
        raise _DuplicateJsonKeyError("JSON object exceeds its field limit")
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError("JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> object:
    del value
    raise _NonStandardJsonConstantError(
        "JSON contains a non-standard numeric constant"
    )


def _parse_json_integer(value: str) -> int:
    if len(value) > 20:
        raise _JsonNumberError("JSON integer exceeds its digit limit")
    try:
        return int(value)
    except ValueError as error:
        raise _JsonNumberError("JSON integer is invalid") from error


def _parse_json_decimal(value: str) -> Decimal:
    if len(value) > _MAX_DECIMAL_CHARACTERS:
        raise _JsonNumberError("JSON decimal exceeds its character limit")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise _JsonNumberError("JSON decimal is invalid") from error
    if not parsed.is_finite():
        raise _JsonNumberError("JSON decimal must be finite")
    return parsed


def _validate_json_structure(
    value: object,
    *,
    limits: ReferenceIOLimits,
) -> None:
    maximum_entries = _required_limit(limits.max_entries, "max_entries")
    maximum_text_bytes = _required_limit(
        limits.max_text_bytes,
        "max_text_bytes",
    )
    pending = [value]
    observed_entries = 0
    observed_text_bytes = 0
    while pending:
        current = pending.pop()
        observed_entries += 1
        if observed_entries > maximum_entries:
            raise OpenAlexProjectionError(
                "OpenAlex JSON exceeds the active entry limit"
            )
        if isinstance(current, str):
            try:
                observed_text_bytes += len(current.encode("utf-8"))
            except UnicodeEncodeError as error:
                raise OpenAlexProjectionError(
                    "OpenAlex JSON contains invalid Unicode text"
                ) from error
            if observed_text_bytes > maximum_text_bytes:
                raise OpenAlexProjectionError(
                    "OpenAlex JSON exceeds the active text byte limit"
                )
        elif isinstance(current, list):
            if len(current) > _MAX_JSON_LIST_ITEMS:
                raise OpenAlexProjectionError(
                    "OpenAlex JSON list exceeds its item limit"
                )
            pending.extend(current)
        elif isinstance(current, dict):
            if len(current) > _MAX_JSON_OBJECT_FIELDS:
                raise OpenAlexProjectionError(
                    "OpenAlex JSON object exceeds its field limit"
                )
            pending.extend(current.values())
            pending.extend(current.keys())


def _works_search_url(request: OpenAlexWorksSearchRequest) -> str:
    query = urlencode(
        (
            ("search", request.query),
            ("page", str(request.page)),
            ("per_page", str(request.per_page)),
            ("select", ",".join(_OPENALEX_SELECT_FIELDS)),
        )
    )
    return f"{OPENALEX_WORKS_ENDPOINT}?{query}"


def _validate_source_url(value: str) -> None:
    _validate_http_url(
        value,
        field="source URL",
        maximum_bytes=_MAX_SOURCE_URL_BYTES,
        require_https=True,
        allow_fragment=False,
    )
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.openalex.org"
        or parsed.path != "/works"
        or "api_key=" in parsed.query.lower()
    ):
        raise OpenAlexProjectionError("OpenAlex source URL is not fixed-origin")


def _validate_http_url(
    value: object,
    *,
    field: str,
    maximum_bytes: int,
    require_https: bool = False,
    allow_fragment: bool = True,
) -> None:
    if not isinstance(value, str) or not value:
        raise OpenAlexProjectionError(f"{field} is invalid")
    size = _provider_text(
        value,
        field=field,
        maximum_bytes=maximum_bytes,
        allow_empty=False,
    )
    if (
        size > maximum_bytes
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise OpenAlexProjectionError(f"{field} is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise OpenAlexProjectionError(f"{field} is invalid") from error
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if (
        parsed.scheme not in allowed_schemes
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or (not allow_fragment and parsed.fragment)
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise OpenAlexProjectionError(f"{field} is invalid")


def _required_provider_text(
    value: object,
    *,
    field: str,
    maximum_bytes: int,
) -> str:
    if not isinstance(value, str):
        raise OpenAlexProjectionError(f"OpenAlex {field} must be text")
    _provider_text(
        value,
        field=field,
        maximum_bytes=maximum_bytes,
        allow_empty=False,
    )
    return value


def _provider_text(
    value: object,
    *,
    field: str,
    maximum_bytes: int,
    allow_empty: bool,
) -> int:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise OpenAlexProjectionError(f"OpenAlex {field} is invalid")
    try:
        observed = bounded_utf8_size(value, max_bytes=maximum_bytes)
    except UnicodeEncodeError as error:
        raise OpenAlexProjectionError(
            f"OpenAlex {field} is not valid Unicode text"
        ) from error
    if observed > maximum_bytes:
        raise OpenAlexProjectionError(
            f"OpenAlex {field} exceeds its byte limit"
        )
    return observed


def _bounded_nonnegative_integer(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= OPENALEX_MAX_COUNT:
        raise OpenAlexProjectionError(f"OpenAlex {field} is invalid")
    return value


def _parse_cost(value: object) -> Decimal | None:
    if value is None:
        return None
    if type(value) is int:
        result = Decimal(value)
    elif isinstance(value, Decimal):
        result = value
    else:
        raise OpenAlexProjectionError("OpenAlex cost_usd is invalid")
    _validate_cost(result)
    return result


def _validate_cost(value: Decimal | None) -> None:
    if value is None:
        return
    if type(value) is not Decimal or not value.is_finite():
        raise OpenAlexProjectionError("OpenAlex cost_usd is invalid")
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise OpenAlexProjectionError("OpenAlex cost_usd exponent is invalid")
    if parts.exponent < -OPENALEX_MAX_COST_DECIMAL_PLACES:
        raise OpenAlexProjectionError(
            "OpenAlex cost_usd exceeds its decimal-place limit"
        )
    if len(parts.digits) > OPENALEX_MAX_COST_FIXED_CHARACTERS:
        raise OpenAlexProjectionError("OpenAlex cost_usd has too many digits")
    if parts.sign != 0:
        raise OpenAlexProjectionError("OpenAlex cost_usd is negative")
    if value < 0 or value > OPENALEX_MAX_COST_USD:
        raise OpenAlexProjectionError("OpenAlex cost_usd is out of bounds")
    expected_characters = _fixed_decimal_characters(value)
    if expected_characters > OPENALEX_MAX_COST_FIXED_CHARACTERS:
        raise OpenAlexProjectionError(
            "OpenAlex cost_usd fixed-point rendering is oversized"
        )
    rendered = format(value, "f")
    if len(rendered) != expected_characters:
        raise OpenAlexProjectionError(
            "OpenAlex cost_usd fixed-point rendering is inconsistent"
        )


def _fixed_decimal_characters(value: Decimal) -> int:
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise OpenAlexProjectionError("OpenAlex cost_usd exponent is invalid")
    if value.is_zero() and parts.exponent >= 0:
        return 1
    digit_count = len(parts.digits)
    if parts.exponent >= 0:
        return digit_count + parts.exponent
    point_position = digit_count + parts.exponent
    if point_position > 0:
        return digit_count + 1
    return 2 - parts.exponent


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise OpenAlexProjectionError("retrieval time is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise OpenAlexProjectionError("retrieval time is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OpenAlexProjectionError("retrieval time requires a UTC offset")
    return parsed.astimezone(UTC)


def _validate_api_key(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_API_KEY_CHARACTERS
        or _contains_control_text(value)
    ):
        raise ValueError("OpenAlex API key is invalid")
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("OpenAlex API key is invalid") from None
    return value


def _validate_user_agent(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("OpenAlex user agent is invalid")
    if _contains_control_text(value):
        raise ValueError("OpenAlex user agent is invalid")
    try:
        observed = bounded_utf8_size(value, max_bytes=_MAX_USER_AGENT_BYTES)
    except UnicodeEncodeError as error:
        raise ValueError("OpenAlex user agent is invalid") from error
    if observed > _MAX_USER_AGENT_BYTES:
        raise ValueError("OpenAlex user agent is invalid")
    return value


def _contains_control_text(value: str) -> bool:
    return any(
        ord(character) < 32 or 127 <= ord(character) <= 159
        for character in value
    )


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"OpenAlex I/O limits must define {name}")
    return value


def _read_bounded_body(
    response: object,
    request: OpenAlexTransportRequest,
) -> bytes:
    read = getattr(response, "read", None)
    if not callable(read):
        raise OpenAlexUnavailableError("OpenAlex response is not readable")
    body = read(request.max_response_bytes + 1)
    if not isinstance(body, bytes):
        raise OpenAlexProjectionError("OpenAlex response body must be bytes")
    if len(body) > request.max_response_bytes:
        raise OpenAlexProjectionError(
            "OpenAlex response exceeds its byte limit"
        )
    return body


def _parse_retry_after(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdigit():
        return None
    parsed = int(value)
    return parsed if 0 <= parsed <= 86_400 else None
