from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from projectkoios.references.enrichment import (
    CACHE_SCHEMA_VERSION,
    MAX_CACHE_BYTES,
    MAX_RESPONSE_BYTES,
    OBSERVATION_GENERATOR_VERSION,
    CacheStatus,
    CrossrefClient,
    DeliveryStatus,
    DiscrepancyKind,
    MetadataEnrichment,
    MetadataProvider,
    NormalizedRequestIdentity,
    ProviderCacheConflictError,
    ProviderCacheError,
    ProviderError,
    ProviderResponseError,
    ResponseObservationEnvelope,
    TransportRequest,
    TransportResponse,
    compare_provider_enrichments,
    normalize_persistent_identifier,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "crossref-response-v1.json"
_RETRIEVED_AT = "2026-02-03T04:05:06+00:00"


@dataclass
class FakeTransport:
    responses: list[TransportResponse]
    requests: list[TransportRequest] = field(default_factory=list)

    def get(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected provider transport call")
        return self.responses.pop(0)


@dataclass(frozen=True)
class SyntheticProvider:
    provider_name: str = "synthetic-provider"
    parser_version: str = "synthetic-parser-v1"

    def fetch(
        self,
        identifier: str | NormalizedRequestIdentity,
        *,
        refresh: bool = False,
    ) -> MetadataEnrichment:
        del refresh
        request = (
            identifier
            if isinstance(identifier, NormalizedRequestIdentity)
            else NormalizedRequestIdentity("synthetic", identifier)
        )
        body = b"{}"
        observation = ResponseObservationEnvelope(
            schema_version=CACHE_SCHEMA_VERSION,
            request_identity=request,
            provider=self.provider_name,
            retrieved_at=_RETRIEVED_AT,
            source_url=(
                f"https://metadata.example.invalid/items/{request.value}"
            ),
            response_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=len(body),
            parser_version=self.parser_version,
            generator_version=OBSERVATION_GENERATOR_VERSION,
            cache_status=CacheStatus.DISABLED,
        )
        return MetadataEnrichment(
            observation=observation,
            delivery_status=DeliveryStatus.PROVIDER_RESPONSE,
            provider_fields=(),
            normalized_proposals=(),
            discrepancies=(),
        )


def _response(
    body: bytes, retrieved_at: str = _RETRIEVED_AT
) -> TransportResponse:
    return TransportResponse(body=body, retrieved_at=retrieved_at)


def _fixture_bytes() -> bytes:
    return _FIXTURE.read_bytes()


def _client(
    tmp_path: Path,
    *responses: TransportResponse,
) -> tuple[CrossrefClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = CrossrefClient(
        cache_directory=tmp_path / "cache",
        transport=transport,
    )
    return client, transport


def _cache_files(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "cache" / "crossref").glob("*.json"))


def _replace_cache_payload(path: Path, payload: object) -> Path:
    request_digest = path.name.split("-")[1]
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    cache_generation = path.name.split("-")[0]
    replacement = path.with_name(
        f"{cache_generation}-{request_digest}-"
        f"{hashlib.sha256(content).hexdigest()}.json"
    )
    path.unlink()
    replacement.write_bytes(content)
    return replacement


def test__provider_protocol__accepts_non_crossref_envelope() -> None:
    provider: MetadataProvider = SyntheticProvider()
    request = NormalizedRequestIdentity("synthetic", "item-1")

    result = provider.fetch(request)

    assert isinstance(provider, MetadataProvider)
    assert result.observation.provider == "synthetic-provider"
    assert result.observation.parser_version == "synthetic-parser-v1"
    assert result.observation.source_url == (
        "https://metadata.example.invalid/items/item-1"
    )
    assert result.observation.request_identity == request


@pytest.mark.parametrize(
    "source_url",
    (
        "http://metadata.example.invalid/items/item-1",
        "https://user@metadata.example.invalid/items/item-1",
        "https://metadata.example.invalid/items/item-1#fragment",
        "https://metadata.example.invalid/items/item 1",
    ),
)
def test__observation_envelope__rejects_unsafe_source_urls(
    source_url: str,
) -> None:
    body = b"{}"
    with pytest.raises(ProviderCacheError, match="source URL"):
        ResponseObservationEnvelope(
            schema_version=CACHE_SCHEMA_VERSION,
            request_identity=NormalizedRequestIdentity("synthetic", "item-1"),
            provider="synthetic-provider",
            retrieved_at=_RETRIEVED_AT,
            source_url=source_url,
            response_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=len(body),
            parser_version="synthetic-parser-v1",
            generator_version=OBSERVATION_GENERATOR_VERSION,
            cache_status=CacheStatus.DISABLED,
        )


def test__crossref__normalizes_request_and_keeps_verbatim_fields_separate(
    tmp_path: Path,
) -> None:
    body = _fixture_bytes()
    client, transport = _client(tmp_path, _response(body))

    result = client.fetch(" HTTPS://doi.org/10.1234/EXAMPLE.ONE ")

    assert isinstance(client, MetadataProvider)
    assert (
        result.observation.request_identity.canonical
        == "doi:10.1234/example.one"
    )
    assert transport.requests[0].url == (
        "https://api.crossref.org/works/10.1234%2Fexample.one"
    )
    assert transport.requests[0].max_response_bytes == MAX_RESPONSE_BYTES
    assert result.observation.retrieved_at == _RETRIEVED_AT
    assert (
        result.observation.response_sha256 == hashlib.sha256(body).hexdigest()
    )
    assert result.observation.response_bytes == len(body)
    assert (
        result.observation.effective_limits
        == transport.requests[0].effective_limits
    )
    assert (
        result.observation.effective_limits_id
        == result.observation.effective_limits.evidence_id
    )
    assert result.delivery_status == DeliveryStatus.PROVIDER_RESPONSE
    assert result.title == "A Synthetic Study"
    assert result.authors == ("Ada Example", "Bo Test")
    assert result.year == "2026"
    assert result.abstract is None
    assert result.abstract_hash is None
    assert result.abstract_status == "not-available"
    fields = {item.name: item for item in result.provider_fields}
    assert fields["DOI"].value_json == '"10.1234/EXAMPLE.ONE"'
    assert fields["title"].value_json == '["  A Synthetic Study  "]'
    assert fields["abstract"].present is False
    assert fields["abstract"].value_json is None
    assert result.proposal("doi") == ("10.1234/example.one",)
    assert result.discrepancies == ()


def test__crossref__cache_replay_preserves_original_observation_exactly(
    tmp_path: Path,
) -> None:
    first_client, _ = _client(tmp_path, _response(_fixture_bytes()))
    first = first_client.fetch("doi:10.1234/EXAMPLE.ONE")
    files_before = _cache_files(tmp_path)
    snapshots = [
        (path.name, path.read_bytes(), path.stat().st_mtime_ns)
        for path in files_before
    ]

    replay_client, replay_transport = _client(tmp_path)
    replay = replay_client.fetch("10.1234/example.one")

    assert replay.observation == first.observation
    assert replay.observation.retrieved_at == _RETRIEVED_AT
    assert replay.delivery_status == DeliveryStatus.CACHE_REPLAY
    assert replay_transport.requests == []
    assert [
        (path.name, path.read_bytes(), path.stat().st_mtime_ns)
        for path in _cache_files(tmp_path)
    ] == snapshots


def test__crossref__changed_response_creates_observation_without_overwrite(
    tmp_path: Path,
) -> None:
    first_body = _fixture_bytes()
    changed = json.loads(first_body)
    changed["message"]["title"] = ["Different Synthetic Title"]
    second_body = json.dumps(changed, separators=(",", ":")).encode()
    client, _ = _client(
        tmp_path,
        _response(first_body),
        _response(second_body, "2026-02-04T04:05:06+00:00"),
    )

    first = client.fetch("10.1234/example.one")
    second = client.fetch("10.1234/example.one", refresh=True)

    assert len(_cache_files(tmp_path)) == 2
    assert (
        first.observation.response_sha256 != second.observation.response_sha256
    )
    assert first.title == "A Synthetic Study"
    assert second.title == "Different Synthetic Title"
    discrepancies = compare_provider_enrichments(first, second)
    assert len(discrepancies) == 1
    assert discrepancies[0].field == "title"
    assert discrepancies[0].kind == DiscrepancyKind.PROVIDER_CONFLICT

    replay, transport = _client(tmp_path)
    assert (
        replay.fetch("10.1234/example.one").title == "Different Synthetic Title"
    )
    assert transport.requests == []


def test__crossref__identical_atomic_publication_is_idempotent(
    tmp_path: Path,
) -> None:
    response = _response(_fixture_bytes())
    client, _ = _client(tmp_path, response, response)

    first = client.fetch("10.1234/example.one")
    second = client.fetch("10.1234/example.one", refresh=True)

    assert first.observation == second.observation
    assert len(_cache_files(tmp_path)) == 1


def test__crossref__equal_time_conflicting_observations_fail_closed(
    tmp_path: Path,
) -> None:
    changed = json.loads(_fixture_bytes())
    changed["message"]["title"] = ["Conflicting title"]
    changed_body = json.dumps(changed, separators=(",", ":")).encode()
    client, _ = _client(
        tmp_path,
        _response(_fixture_bytes()),
        _response(changed_body),
    )
    client.fetch("10.1234/example.one")
    client.fetch("10.1234/example.one", refresh=True)

    replay, transport = _client(tmp_path)
    with pytest.raises(
        ProviderCacheConflictError, match="latest retrieval time"
    ):
        replay.fetch("10.1234/example.one")
    assert transport.requests == []
    assert len(_cache_files(tmp_path)) == 2


def test__crossref__provider_absence_does_not_invent_metadata_or_abstract(
    tmp_path: Path,
) -> None:
    body = b'{"status":"ok","message":{"unknown-provider-field":true}}'
    client, _ = _client(tmp_path, _response(body))

    result = client.fetch("10.1234/absent")

    assert result.normalized_proposals == ()
    assert result.title is None
    assert result.authors == ()
    assert result.year is None
    assert result.abstract is None
    assert all(not field.present for field in result.provider_fields)


def test__crossref__request_provider_identifier_conflict_is_typed(
    tmp_path: Path,
) -> None:
    payload = {"status": "ok", "message": {"DOI": "10.1234/other"}}
    body = json.dumps(payload).encode()
    client, _ = _client(tmp_path, _response(body))

    result = client.fetch("10.1234/requested")

    assert result.doi == "10.1234/requested"
    assert result.proposal("doi") == ("10.1234/other",)
    assert result.discrepancies[0].kind == (
        DiscrepancyKind.REQUEST_PROVIDER_CONFLICT
    )
    assert result.discrepancies[0].values[0].source == "request"
    assert result.discrepancies[0].values[1].source == "crossref"


@pytest.mark.parametrize(
    "value",
    (
        "10.1234/EXAMPLE.ONE",
        "doi: 10.1234/example.one",
        "https://doi.org/10.1234/EXAMPLE.ONE",
        "http://dx.doi.org/10.1234/example.one",
    ),
)
def test__identifier_normalization__is_scheme_specific(value: str) -> None:
    identity = normalize_persistent_identifier(" DOI ", value)
    assert identity.canonical == "doi:10.1234/example.one"


def test__identifier_normalization__rejects_unknown_or_empty_values() -> None:
    with pytest.raises(ProviderError, match="unsupported"):
        normalize_persistent_identifier("arxiv", "2401.00001")
    with pytest.raises(ProviderError, match="non-empty"):
        normalize_persistent_identifier("doi", "  ")


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "unknown",
        "observation",
        "parser-version",
        "generator-version",
        "provider",
        "source-url",
    ],
)
def test__crossref__incompatible_cache_schema_fails_without_repair(
    tmp_path: Path,
    mutation: str,
) -> None:
    client, _ = _client(tmp_path, _response(_fixture_bytes()))
    client.fetch("10.1234/example.one")
    original = _cache_files(tmp_path)[0]
    payload = json.loads(original.read_bytes())
    if mutation == "version":
        payload["schema_version"] = CACHE_SCHEMA_VERSION + 1
    elif mutation == "unknown":
        payload["unknown"] = True
    elif mutation == "observation":
        payload["observation"]["unknown"] = True
    elif mutation == "parser-version":
        payload["observation"]["parser_version"] = "unknown-parser-v99"
    elif mutation == "generator-version":
        payload["observation"]["generator_version"] = "unknown-generator-v99"
    elif mutation == "provider":
        payload["observation"]["provider"] = "synthetic-provider"
    else:
        payload["observation"]["source_url"] = (
            "https://metadata.example.invalid/items/item-1"
        )
    altered = _replace_cache_payload(original, payload)
    before = altered.read_bytes()

    replay, transport = _client(tmp_path)
    with pytest.raises(ProviderCacheError):
        replay.fetch("10.1234/example.one")

    assert transport.requests == []
    assert altered.read_bytes() == before
    assert _cache_files(tmp_path) == [altered]


@pytest.mark.parametrize("content", [b"{", b"null", b"[]", b'{"partial":true}'])
def test__crossref__malformed_or_partial_cache_fails_closed(
    tmp_path: Path,
    content: bytes,
) -> None:
    request_digest = hashlib.sha256(b"doi:10.1234/example.one").hexdigest()
    cache = tmp_path / "cache" / "crossref"
    cache.mkdir(parents=True)
    path = cache / (
        f"v2-{request_digest}-{hashlib.sha256(content).hexdigest()}.json"
    )
    path.write_bytes(content)

    replay, transport = _client(tmp_path)
    with pytest.raises(ProviderCacheError):
        replay.fetch("10.1234/example.one")
    assert transport.requests == []
    assert path.read_bytes() == content


def test__crossref__legacy_request_cache_blocks_transport_fallback(
    tmp_path: Path,
) -> None:
    request_digest = hashlib.sha256(b"doi:10.1234/example.one").hexdigest()
    cache = tmp_path / "cache" / "crossref"
    cache.mkdir(parents=True)
    content = b"{}"
    path = cache / (
        f"v1-{request_digest}-{hashlib.sha256(content).hexdigest()}.json"
    )
    path.write_bytes(content)

    replay, transport = _client(tmp_path)
    with pytest.raises(ProviderCacheError, match="legacy"):
        replay.fetch("10.1234/example.one")
    assert transport.requests == []
    assert path.read_bytes() == content


def test__crossref__cache_content_identity_conflict_fails_without_repair(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, _response(_fixture_bytes()))
    client.fetch("10.1234/example.one")
    path = _cache_files(tmp_path)[0]
    original = path.read_bytes()
    altered = (
        original[:-2] + (b"X" if original[-2:-1] != b"X" else b"Y") + b"\n"
    )
    path.write_bytes(altered)

    replay, transport = _client(tmp_path)
    with pytest.raises(ProviderCacheConflictError, match="content hash"):
        replay.fetch("10.1234/example.one")

    assert transport.requests == []
    assert path.read_bytes() == altered


def test__crossref__oversized_cache_fails_closed_without_transport(
    tmp_path: Path,
) -> None:
    request_digest = hashlib.sha256(b"doi:10.1234/example.one").hexdigest()
    cache = tmp_path / "cache" / "crossref"
    cache.mkdir(parents=True)
    content = b"x" * (MAX_CACHE_BYTES + 1)
    path = cache / (
        f"v2-{request_digest}-{hashlib.sha256(content).hexdigest()}.json"
    )
    path.write_bytes(content)

    replay, transport = _client(tmp_path)
    with pytest.raises(ProviderCacheError, match="safely read"):
        replay.fetch("10.1234/example.one")
    assert transport.requests == []
    assert path.stat().st_size == MAX_CACHE_BYTES + 1


def test__crossref__symlinked_cache_entry_fails_path_confinement(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    cache = tmp_path / "cache" / "crossref"
    (cache / "unsafe.json").symlink_to(outside)

    with pytest.raises(ProviderCacheError, match="unsafe"):
        client.fetch("10.1234/example.one")
    assert outside.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize(
    "body",
    (
        b"not-json",
        b'{"status":"ok","message":[]}',
        b'{"status":"ok","message":{"title":"not-a-list"}}',
    ),
)
def test__crossref__invalid_provider_response_leaves_no_partial_entry(
    tmp_path: Path,
    body: bytes,
) -> None:
    client, _ = _client(tmp_path, _response(body))

    with pytest.raises(ProviderResponseError):
        client.fetch("10.1234/example.one")

    assert _cache_files(tmp_path) == []


@pytest.mark.parametrize(
    "body",
    (
        b'{"message":{}}',
        b'{"status":"failed","message":{}}',
        b'{"status":null,"message":{}}',
        b'{"status":1,"message":{}}',
    ),
)
def test__crossref__requires_explicit_success_before_recording_absence(
    tmp_path: Path,
    body: bytes,
) -> None:
    client, _ = _client(tmp_path, _response(body))

    with pytest.raises(ProviderResponseError, match="status"):
        client.fetch("10.1234/example.one")

    assert _cache_files(tmp_path) == []


@pytest.mark.parametrize("constant", (b"NaN", b"Infinity", b"-Infinity"))
def test__crossref__rejects_nonstandard_json_constants_before_publication(
    tmp_path: Path,
    constant: bytes,
) -> None:
    body = b'{"status":"ok","message":{"title":[' + constant + b"]}}"
    client, _ = _client(tmp_path, _response(body))

    with pytest.raises(ProviderResponseError, match="valid UTF-8 JSON"):
        client.fetch("10.1234/example.one")

    assert _cache_files(tmp_path) == []


def test__crossref__duplicate_response_keys_are_response_errors(
    tmp_path: Path,
) -> None:
    body = b'{"status":"ok","message":{},"message":{}}'
    client, _ = _client(tmp_path, _response(body))

    with pytest.raises(ProviderResponseError, match="valid UTF-8 JSON"):
        client.fetch("10.1234/example.one")

    assert _cache_files(tmp_path) == []


def test__crossref__response_and_field_bounds_fail_before_publication(
    tmp_path: Path,
) -> None:
    oversized = b"{" + b" " * MAX_RESPONSE_BYTES + b"}"
    client, _ = _client(tmp_path, _response(oversized))
    with pytest.raises(ProviderResponseError, match="byte limit"):
        client.fetch("10.1234/example.one")
    assert _cache_files(tmp_path) == []

    many_authors = {
        "status": "ok",
        "message": {
            "author": [
                {"given": "Synthetic", "family": str(index)}
                for index in range(1025)
            ]
        },
    }
    bounded, _ = _client(
        tmp_path / "other",
        _response(json.dumps(many_authors).encode()),
    )
    with pytest.raises(ProviderResponseError, match="author list"):
        bounded.fetch("10.1234/example.one")
    assert _cache_files(tmp_path / "other") == []
