from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

import pytest
from projectkoios.references.openalex import (
    OPENALEX_MAX_AUTHORS_PER_WORK,
    OPENALEX_MAX_COST_DECIMAL_PLACES,
    OPENALEX_MAX_COST_FIXED_CHARACTERS,
    OPENALEX_MAX_COST_USD,
    OPENALEX_MAX_COUNT,
    OPENALEX_MAX_RESPONSE_BYTES,
    OPENALEX_WORKS_PARSER_VERSION,
    OPENALEX_WORKS_SEARCH_IO_LIMITS,
    OpenAlexProjectionError,
    OpenAlexRateLimitError,
    OpenAlexTransportRequest,
    OpenAlexTransportResponse,
    OpenAlexUnavailableError,
    OpenAlexUpstreamError,
    OpenAlexWorksClient,
    OpenAlexWorksProvider,
    OpenAlexWorksSearchRequest,
    OpenAlexWorksSearchRequestError,
    create_openalex_works_provider,
)

_RETRIEVED_AT = "2026-11-26T01:02:03+00:00"
_API_KEY = "synthetic-openalex-secret-key"


@dataclass
class FakeTransport:
    responses: list[OpenAlexTransportResponse]
    requests: list[OpenAlexTransportRequest] = field(default_factory=list)

    def get(
        self,
        request: OpenAlexTransportRequest,
    ) -> OpenAlexTransportResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected OpenAlex transport request")
        return self.responses.pop(0)


class UnavailableTransport:
    def get(
        self,
        request: OpenAlexTransportRequest,
    ) -> OpenAlexTransportResponse:
        del request
        raise TimeoutError("synthetic timeout")


def _work(
    *,
    work_id: str = "https://openalex.org/W123456789",
    title: str = "<script>A provider title</script>",
    authorships: Sequence[object] | None = None,
    primary_location: object = None,
    cited_by_count: int = 42,
) -> dict[str, object]:
    if authorships is None:
        authorships = [
            {
                "author_position": "first",
                "author": {
                    "id": "https://openalex.org/A123",
                    "display_name": "Ada <b>Example</b>",
                },
                "institutions": [],
            },
            {
                "author_position": "last",
                "author": {
                    "id": "https://openalex.org/A456",
                    "display_name": "Bo Test",
                },
                "institutions": [],
            },
        ]
    if primary_location is None:
        primary_location = {
            "landing_page_url": "https://doi.org/10.1234/example",
            "pdf_url": None,
            "source": {
                "id": "https://openalex.org/S123",
                "display_name": "Journal <i>Example</i>",
            },
        }
    return {
        "id": work_id,
        "title": title,
        "publication_year": 2026,
        "type": "article",
        "doi": "https://doi.org/10.1234/EXAMPLE",
        "authorships": list(authorships),
        "primary_location": primary_location,
        "cited_by_count": cited_by_count,
    }


def _body(
    *,
    works: Sequence[object] | None = None,
    count: int = 1,
    page: int = 1,
    per_page: int = 25,
    cost: object = 0.001,
) -> bytes:
    payload = {
        "meta": {
            "count": count,
            "page": page,
            "per_page": per_page,
            "cost_usd": cost,
            "db_response_time_ms": 7,
        },
        "results": [_work()] if works is None else list(works),
        "group_by": [],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _response(
    body: bytes,
    *,
    status_code: int = 200,
    retry_after_seconds: int | None = None,
    content_encoding: str | None = None,
) -> OpenAlexTransportResponse:
    return OpenAlexTransportResponse(
        status_code=status_code,
        body=body,
        retrieved_at=_RETRIEVED_AT,
        retry_after_seconds=retry_after_seconds,
        content_encoding=content_encoding,
    )


def test__openalex_request__normalizes_query_and_enforces_basic_paging() -> (
    None
):
    request = OpenAlexWorksSearchRequest(
        "  density functional theory  ",
        page=100,
        per_page=100,
    )
    assert request.query == "density functional theory"
    assert request.page == 100
    assert request.per_page == 100

    invalid = (
        {"query": ""},
        {"query": "x" * 501},
        {"query": "unsafe\nquery"},
        {"query": "valid", "page": True},
        {"query": "valid", "page": 101, "per_page": 100},
        {"query": "valid", "per_page": 101},
    )
    for values in invalid:
        with pytest.raises(OpenAlexWorksSearchRequestError):
            OpenAlexWorksSearchRequest(**values)


def test__openalex__anonymous_search_uses_fixed_selected_first_page() -> None:
    body = _body()
    transport = FakeTransport([_response(body)])
    provider = OpenAlexWorksClient(transport=transport)
    request = OpenAlexWorksSearchRequest("quantum materials")

    result = provider.search_works(request)

    assert isinstance(provider, OpenAlexWorksProvider)
    assert len(transport.requests) == 1
    observed_request = transport.requests[0]
    assert observed_request.url.startswith(
        "https://api.openalex.org/works?search=quantum+materials&"
    )
    assert "page=1" in observed_request.url
    assert "per_page=25" in observed_request.url
    assert (
        "select=id%2Ctitle%2Cpublication_year%2Ctype%2Cdoi%2Cauthorships%2C"
        "primary_location%2Ccited_by_count"
    ) in observed_request.url
    assert "api_key" not in observed_request.url
    assert observed_request.has_api_key is False
    assert result.total_count == 1
    assert result.page == 1
    assert result.per_page == 25
    assert result.cost_usd == Decimal("0.001")
    assert len(result.works) == 1
    work = result.works[0]
    assert work.work_id == "https://openalex.org/W123456789"
    assert work.title == "<script>A provider title</script>"
    assert work.publication_year == 2026
    assert work.work_type == "article"
    assert work.doi == "https://doi.org/10.1234/EXAMPLE"
    assert work.authors == ("Ada <b>Example</b>", "Bo Test")
    assert work.primary_source_display_name == "Journal <i>Example</i>"
    assert work.cited_by_count == 42
    assert work.landing_url == "https://doi.org/10.1234/example"
    assert result.provenance.request == request
    assert result.provenance.provider == "openalex"
    assert result.provenance.parser_version == OPENALEX_WORKS_PARSER_VERSION
    assert result.provenance.source_url == observed_request.url
    assert result.provenance.response_bytes == len(body)
    assert result.provenance.response_sha256 == hashlib.sha256(body).hexdigest()
    assert result.provenance.effective_limits == OPENALEX_WORKS_SEARCH_IO_LIMITS
    assert result.provenance.effective_limits_id == (
        OPENALEX_WORKS_SEARCH_IO_LIMITS.evidence_id
    )
    assert result.provenance.observation_id.startswith(
        "openalex-works-search:sha256:"
    )


def test__openalex__optional_key_is_bearer_only_and_never_identity() -> None:
    body = _body()
    transport = FakeTransport([_response(body), _response(body)])
    provider = OpenAlexWorksClient(api_key=_API_KEY, transport=transport)
    request = OpenAlexWorksSearchRequest("credential isolation")

    assert not hasattr(provider, "__dict__")
    assert _API_KEY not in repr(provider)
    first = provider.search_works(request)
    second = provider.search_works(request)

    observed_request = transport.requests[0]
    assert observed_request.has_api_key is True
    assert observed_request._headers_for_transport()["Authorization"] == (
        f"Bearer {_API_KEY}"
    )
    assert _API_KEY not in repr(observed_request)
    assert _API_KEY not in observed_request.url
    assert _API_KEY not in first.provenance.source_url
    assert _API_KEY not in first.provenance.observation_id
    assert first.provenance == second.provenance
    assert first.provenance.observation_id == second.provenance.observation_id


def test__openalex__missing_location_uses_work_id_as_landing_url() -> None:
    work = _work(primary_location={"source": None, "landing_page_url": None})
    transport = FakeTransport([_response(_body(works=[work]))])

    result = OpenAlexWorksClient(transport=transport).search_works(
        OpenAlexWorksSearchRequest("fallback landing")
    )

    assert result.works[0].primary_source_display_name is None
    assert result.works[0].landing_url == result.works[0].work_id


def test__openalex__absent_cost_is_none() -> None:
    payload = json.loads(_body())
    del payload["meta"]["cost_usd"]
    transport = FakeTransport(
        [_response(json.dumps(payload, separators=(",", ":")).encode())]
    )

    result = OpenAlexWorksClient(transport=transport).search_works(
        OpenAlexWorksSearchRequest("no reported cost")
    )

    assert result.cost_usd is None


def test__openalex__cost_has_bounded_exact_fixed_point_rendering() -> None:
    transport = FakeTransport([_response(_body())])
    result = OpenAlexWorksClient(transport=transport).search_works(
        OpenAlexWorksSearchRequest("bounded cost")
    )

    smallest = Decimal(1).scaleb(-OPENALEX_MAX_COST_DECIMAL_PLACES)
    assert replace(result, cost_usd=smallest).cost_usd == smallest
    maximum_scaled = Decimal("1000000.00000000")
    assert maximum_scaled == OPENALEX_MAX_COST_USD
    bounded = replace(result, cost_usd=maximum_scaled)
    assert bounded.cost_usd is not None
    rendered = format(bounded.cost_usd, "f")
    assert len(rendered) == OPENALEX_MAX_COST_FIXED_CHARACTERS

    for invalid in (
        Decimal("1e-9"),
        Decimal("1e-100000"),
        Decimal("0e-100000"),
    ):
        with pytest.raises(OpenAlexProjectionError, match="decimal-place"):
            replace(result, cost_usd=invalid)

    marker = b'"cost_usd":0.001'
    body = _body()
    assert marker in body
    exponent_bomb = body.replace(marker, b'"cost_usd":1e-100000')
    with pytest.raises(OpenAlexProjectionError, match="decimal-place"):
        OpenAlexWorksClient(
            transport=FakeTransport([_response(exponent_bomb)])
        ).search_works(OpenAlexWorksSearchRequest("provider exponent bomb"))


def test__openalex_factory__returns_stable_provider_protocol() -> None:
    provider = create_openalex_works_provider(
        transport=FakeTransport([_response(_body())])
    )

    assert isinstance(provider, OpenAlexWorksProvider)
    result = provider.search_works(OpenAlexWorksSearchRequest("factory"))
    assert result.works[0].title == "<script>A provider title</script>"


@pytest.mark.parametrize(
    "body",
    (
        b"not-json",
        b'{"meta":{},"results":[],"group_by":[],"unknown":true}',
        b'{"meta":{"count":0,"page":1,"per_page":25},'
        b'"results":[],"results":[],"group_by":[]}',
        b'{"meta":{"count":NaN,"page":1,"per_page":25},'
        b'"results":[],"group_by":[]}',
        b"[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]",
    ),
)
def test__openalex__rejects_non_strict_or_deep_json(body: bytes) -> None:
    transport = FakeTransport([_response(body)])
    with pytest.raises(OpenAlexProjectionError):
        OpenAlexWorksClient(transport=transport).search_works(
            OpenAlexWorksSearchRequest("strict json")
        )


def test__openalex__rejects_unknown_or_missing_selected_work_fields() -> None:
    unknown = _work()
    unknown["abstract"] = "not selected"
    missing = _work()
    del missing["type"]

    for work in (unknown, missing):
        transport = FakeTransport([_response(_body(works=[work]))])
        with pytest.raises(
            OpenAlexProjectionError, match="selected work fields"
        ):
            OpenAlexWorksClient(transport=transport).search_works(
                OpenAlexWorksSearchRequest("selected fields")
            )


def test__openalex__bounds_result_and_author_lists() -> None:
    too_many_results = [
        _work(work_id=f"https://openalex.org/W{index + 1}")
        for index in range(2)
    ]
    transport = FakeTransport(
        [_response(_body(works=too_many_results, count=2, per_page=1))]
    )
    with pytest.raises(OpenAlexProjectionError, match="page size"):
        OpenAlexWorksClient(transport=transport).search_works(
            OpenAlexWorksSearchRequest("result bound", per_page=1)
        )

    too_many_authors = [
        {"author": {"display_name": f"Author {index}"}}
        for index in range(OPENALEX_MAX_AUTHORS_PER_WORK + 1)
    ]
    transport = FakeTransport(
        [_response(_body(works=[_work(authorships=too_many_authors)]))]
    )
    with pytest.raises(OpenAlexProjectionError, match="authorships"):
        OpenAlexWorksClient(transport=transport).search_works(
            OpenAlexWorksSearchRequest("author bound")
        )


def test__openalex__bounds_response_bytes_and_content_encoding() -> None:
    transport = FakeTransport(
        [_response(b"x" * (OPENALEX_MAX_RESPONSE_BYTES + 1))]
    )
    with pytest.raises(OpenAlexProjectionError, match="byte limit"):
        OpenAlexWorksClient(transport=transport).search_works(
            OpenAlexWorksSearchRequest("byte bound")
        )

    transport = FakeTransport([_response(_body(), content_encoding="gzip")])
    with pytest.raises(OpenAlexProjectionError, match="content encoding"):
        OpenAlexWorksClient(transport=transport).search_works(
            OpenAlexWorksSearchRequest("encoding bound")
        )


def test__openalex__tightened_profile_dimensions_are_enforced() -> None:
    depth_limits = replace(
        OPENALEX_WORKS_SEARCH_IO_LIMITS,
        max_json_depth=3,
    )
    transport = FakeTransport([_response(_body())])
    with pytest.raises(OpenAlexProjectionError, match="strict UTF-8 JSON"):
        OpenAlexWorksClient(
            transport=transport,
            limits=depth_limits,
        ).search_works(OpenAlexWorksSearchRequest("depth bound"))

    entry_limits = replace(
        OPENALEX_WORKS_SEARCH_IO_LIMITS,
        max_entries=10,
    )
    with pytest.raises(OpenAlexProjectionError, match="entry limit"):
        OpenAlexWorksClient(
            transport=FakeTransport([_response(_body())]),
            limits=entry_limits,
        ).search_works(OpenAlexWorksSearchRequest("entry bound"))

    text_limits = replace(
        OPENALEX_WORKS_SEARCH_IO_LIMITS,
        max_text_bytes=10,
    )
    with pytest.raises(OpenAlexProjectionError, match="text byte limit"):
        OpenAlexWorksClient(
            transport=FakeTransport([_response(_body())]),
            limits=text_limits,
        ).search_works(OpenAlexWorksSearchRequest("text bound"))

    result_limits = replace(
        OPENALEX_WORKS_SEARCH_IO_LIMITS,
        max_candidates=1,
    )
    with pytest.raises(OpenAlexWorksSearchRequestError, match="active"):
        OpenAlexWorksClient(
            transport=FakeTransport([]),
            limits=result_limits,
        ).search_works(OpenAlexWorksSearchRequest("result limit", per_page=2))


def test__openalex__shared_count_bound_applies_to_result_and_work() -> None:
    accepted = FakeTransport(
        [
            _response(
                _body(
                    works=[_work(cited_by_count=OPENALEX_MAX_COUNT)],
                    count=OPENALEX_MAX_COUNT,
                )
            )
        ]
    )
    result = OpenAlexWorksClient(transport=accepted).search_works(
        OpenAlexWorksSearchRequest("count boundary")
    )
    assert result.total_count == OPENALEX_MAX_COUNT
    assert result.works[0].cited_by_count == OPENALEX_MAX_COUNT

    excessive_total = FakeTransport(
        [_response(_body(count=OPENALEX_MAX_COUNT + 1))]
    )
    with pytest.raises(OpenAlexProjectionError, match="total count"):
        OpenAlexWorksClient(transport=excessive_total).search_works(
            OpenAlexWorksSearchRequest("total count boundary")
        )

    excessive_citations = FakeTransport(
        [_response(_body(works=[_work(cited_by_count=OPENALEX_MAX_COUNT + 1)]))]
    )
    with pytest.raises(OpenAlexProjectionError, match="cited-by count"):
        OpenAlexWorksClient(transport=excessive_citations).search_works(
            OpenAlexWorksSearchRequest("citation count boundary")
        )


def test__openalex__malformed_transport_metadata_is_projection_error() -> None:
    malformed_encoding = _response(_body())
    object.__setattr__(malformed_encoding, "content_encoding", 7)
    with pytest.raises(OpenAlexProjectionError, match="encoding metadata"):
        OpenAlexWorksClient(
            transport=FakeTransport([malformed_encoding])
        ).search_works(OpenAlexWorksSearchRequest("encoding metadata"))

    malformed_retry = _response(b"{}", status_code=429)
    object.__setattr__(malformed_retry, "retry_after_seconds", -1)
    with pytest.raises(OpenAlexProjectionError, match="retry-after"):
        OpenAlexWorksClient(
            transport=FakeTransport([malformed_retry])
        ).search_works(OpenAlexWorksSearchRequest("retry metadata"))


def test__openalex__maps_rate_limit_upstream_and_unavailable_separately() -> (
    None
):
    rate_transport = FakeTransport(
        [_response(b"{}", status_code=429, retry_after_seconds=7)]
    )
    with pytest.raises(OpenAlexRateLimitError) as rate:
        OpenAlexWorksClient(transport=rate_transport).search_works(
            OpenAlexWorksSearchRequest("rate limit")
        )
    assert rate.value.status_code == 429
    assert rate.value.retry_after_seconds == 7

    upstream_transport = FakeTransport([_response(b"{}", status_code=503)])
    with pytest.raises(OpenAlexUpstreamError) as upstream:
        OpenAlexWorksClient(transport=upstream_transport).search_works(
            OpenAlexWorksSearchRequest("upstream")
        )
    assert upstream.value.status_code == 503

    with pytest.raises(OpenAlexUnavailableError):
        OpenAlexWorksClient(transport=UnavailableTransport()).search_works(
            OpenAlexWorksSearchRequest("unavailable")
        )


def test__openalex__errors_never_include_configured_api_key() -> None:
    transport = FakeTransport([_response(b"{}", status_code=403)])
    client = OpenAlexWorksClient(api_key=_API_KEY, transport=transport)

    with pytest.raises(OpenAlexUpstreamError) as caught:
        client.search_works(OpenAlexWorksSearchRequest("bad credential"))

    assert _API_KEY not in str(caught.value)
    assert _API_KEY not in repr(caught.value)
    assert _API_KEY not in repr(transport.requests[0])

    invalid_key = "synthetic-secret-κλειδί"
    with pytest.raises(ValueError) as invalid:
        OpenAlexWorksClient(api_key=invalid_key, transport=FakeTransport([]))
    assert invalid.value.__cause__ is None
    assert invalid_key not in str(invalid.value)
    assert invalid_key not in repr(invalid.value)
