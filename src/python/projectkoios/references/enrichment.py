from __future__ import annotations

import base64
import binascii
import hashlib
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast, runtime_checkable
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import AuthorizedRoot, PathSafetyError

CACHE_SCHEMA_VERSION = 1
CROSSREF_PARSER_VERSION = "crossref-metadata-v1"
OBSERVATION_GENERATOR_VERSION = "projectkoios-response-observation-v1"
MAX_RESPONSE_BYTES = 2_000_000
MAX_CACHE_BYTES = 3_000_000
_MAX_IDENTIFIER_LENGTH = 512
_MAX_URL_LENGTH = 4096
_MAX_FIELD_BYTES = 512_000
_MAX_TITLES = 32
_MAX_AUTHORS = 1024
_MAX_DATE_PARTS = 16
_TAG = re.compile(r"<[^>]+>")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER_SCHEME = re.compile(r"[a-z][a-z0-9+.-]{0,31}")
_SAFE_COMPONENT = re.compile(r"[a-z][a-z0-9._+-]{0,127}")
_SAFE_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_CACHE_NAME = re.compile(r"v1-([0-9a-f]{64})-([0-9a-f]{64})\.json")


class ProviderError(ValueError):
    """Base error for bounded provider acquisition and parsing."""


class ProviderResponseError(ProviderError):
    """Raised when a provider response is malformed or exceeds its contract."""


class ProviderCacheError(ProviderError):
    """Raised when provider cache evidence is unsafe or incompatible."""


class ProviderCacheConflictError(ProviderCacheError):
    """Raised when cache publication or deterministic replay conflicts."""


class CacheStatus(StrEnum):
    PUBLISHED = "cache-published"
    DISABLED = "cache-disabled"


class DeliveryStatus(StrEnum):
    PROVIDER_RESPONSE = "provider-response"
    CACHE_REPLAY = "cache-replay"


class DiscrepancyKind(StrEnum):
    REQUEST_PROVIDER_CONFLICT = "request-provider-conflict"
    PROVIDER_CONFLICT = "provider-conflict"


@dataclass(frozen=True)
class NormalizedRequestIdentity:
    """An identifier normalized before request and cache identity."""

    scheme: str
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scheme, str)
            or _IDENTIFIER_SCHEME.fullmatch(self.scheme) is None
        ):
            raise ProviderError(
                "identifier scheme is not a safe normalized name"
            )
        if (
            not isinstance(self.value, str)
            or not self.value
            or self.value != self.value.strip()
            or len(self.value) > _MAX_IDENTIFIER_LENGTH
        ):
            raise ProviderError("normalized identifier is empty or oversized")
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in self.value
        ):
            raise ProviderError("normalized identifier contains control text")

    @property
    def canonical(self) -> str:
        return f"{self.scheme}:{self.value}"


def normalize_persistent_identifier(
    scheme: str,
    value: str,
) -> NormalizedRequestIdentity:
    """Normalize one identifier according to an explicitly named scheme."""
    if not isinstance(scheme, str) or not isinstance(value, str):
        raise ProviderError("identifier scheme and value must be strings")
    normalized_scheme = scheme.strip().lower()
    if normalized_scheme != "doi":
        raise ProviderError("unsupported persistent-identifier scheme")
    normalized_value = normalize_doi(value)
    if normalized_value is None:
        raise ProviderError("DOI must be a non-empty string")
    return NormalizedRequestIdentity(normalized_scheme, normalized_value)


@dataclass(frozen=True)
class ResponseObservationEnvelope:
    """Immutable identity and provenance for exact provider response bytes."""

    schema_version: int
    request_identity: NormalizedRequestIdentity
    provider: str
    retrieved_at: str
    source_url: str
    response_sha256: str
    response_bytes: int
    parser_version: str
    generator_version: str
    cache_status: CacheStatus

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != CACHE_SCHEMA_VERSION
        ):
            raise ProviderCacheError("unsupported observation schema version")
        if not isinstance(self.request_identity, NormalizedRequestIdentity):
            raise ProviderCacheError(
                "observation request identity is malformed"
            )
        if (
            not isinstance(self.provider, str)
            or _SAFE_COMPONENT.fullmatch(self.provider) is None
        ):
            raise ProviderCacheError(
                "observation provider is not a safe identifier"
            )
        _parse_timestamp(self.retrieved_at)
        _validate_https_source_url(self.source_url)
        if (
            not isinstance(self.response_sha256, str)
            or _SHA256.fullmatch(self.response_sha256) is None
        ):
            raise ProviderCacheError("response hash is not a SHA-256 digest")
        if (
            type(self.response_bytes) is not int
            or self.response_bytes < 0
            or self.response_bytes > MAX_RESPONSE_BYTES
        ):
            raise ProviderCacheError("response byte size is out of bounds")
        if (
            not isinstance(self.parser_version, str)
            or _SAFE_COMPONENT.fullmatch(self.parser_version) is None
        ):
            raise ProviderCacheError(
                "observation parser version is not a safe identifier"
            )
        if (
            not isinstance(self.generator_version, str)
            or _SAFE_COMPONENT.fullmatch(self.generator_version) is None
        ):
            raise ProviderCacheError(
                "observation generator version is not a safe identifier"
            )
        if not isinstance(
            self.cache_status, CacheStatus
        ) or self.cache_status not in {
            CacheStatus.PUBLISHED,
            CacheStatus.DISABLED,
        }:
            raise ProviderCacheError("observation cache status is incompatible")

    @property
    def observation_id(self) -> str:
        rendered = _canonical_json_bytes(_observation_to_mapping(self))
        return hashlib.sha256(rendered).hexdigest()


@dataclass(frozen=True)
class ProviderField:
    """One provider field retained without applying normalization proposals."""

    name: str
    present: bool
    value_json: str | None

    def __post_init__(self) -> None:
        if not self.name:
            raise ProviderResponseError("provider field name must be non-empty")
        if self.present != (self.value_json is not None):
            raise ProviderResponseError(
                "provider field presence is inconsistent"
            )
        if (
            self.value_json is not None
            and len(self.value_json.encode("utf-8")) > _MAX_FIELD_BYTES
        ):
            raise ProviderResponseError("provider field exceeds its byte limit")


@dataclass(frozen=True)
class NormalizedFieldProposal:
    """A non-authoritative normalized proposal derived from provider text."""

    field: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.field
            or not self.values
            or any(not value for value in self.values)
        ):
            raise ProviderResponseError("normalized proposal must be non-empty")
        if len(self.values) > _MAX_AUTHORS:
            raise ProviderResponseError(
                "normalized proposal exceeds its item limit"
            )
        if sum(len(value.encode("utf-8")) for value in self.values) > (
            _MAX_FIELD_BYTES
        ):
            raise ProviderResponseError(
                "normalized proposal exceeds its byte limit"
            )


@dataclass(frozen=True)
class DiscrepantValue:
    source: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source or not self.values:
            raise ProviderResponseError(
                "discrepant value must identify its source"
            )


@dataclass(frozen=True)
class FieldDiscrepancy:
    """A typed conflict; it is evidence and never an overwrite instruction."""

    field: str
    kind: DiscrepancyKind
    values: tuple[DiscrepantValue, ...]

    def __post_init__(self) -> None:
        if not self.field or len(self.values) < 2:
            raise ProviderResponseError("field discrepancy requires two values")


@dataclass(frozen=True)
class MetadataEnrichment:
    """Parsed proposals plus their immutable response observation."""

    observation: ResponseObservationEnvelope
    delivery_status: DeliveryStatus
    provider_fields: tuple[ProviderField, ...]
    normalized_proposals: tuple[NormalizedFieldProposal, ...]
    discrepancies: tuple[FieldDiscrepancy, ...]

    def proposal(self, field: str) -> tuple[str, ...] | None:
        for proposal in self.normalized_proposals:
            if proposal.field == field:
                return proposal.values
        return None

    @property
    def provider(self) -> str:
        return self.observation.provider

    @property
    def source_url(self) -> str:
        return self.observation.source_url

    @property
    def retrieved_at(self) -> str:
        return self.observation.retrieved_at

    @property
    def doi(self) -> str:
        return self.observation.request_identity.value

    @property
    def title(self) -> str | None:
        values = self.proposal("title")
        return values[0] if values else None

    @property
    def authors(self) -> tuple[str, ...]:
        return self.proposal("authors") or ()

    @property
    def year(self) -> str | None:
        values = self.proposal("year")
        return values[0] if values else None

    @property
    def abstract(self) -> str | None:
        values = self.proposal("abstract")
        return values[0] if values else None

    @property
    def abstract_hash(self) -> str | None:
        value = self.abstract
        return hashlib.sha256(value.encode()).hexdigest() if value else None

    @property
    def abstract_status(self) -> str:
        return (
            "provider-supplied"
            if self.abstract is not None
            else "not-available"
        )


@dataclass(frozen=True)
class TransportRequest:
    url: str
    headers: tuple[tuple[str, str], ...]
    timeout_seconds: float
    max_response_bytes: int


@dataclass(frozen=True)
class TransportResponse:
    body: bytes
    retrieved_at: str


class MetadataTransport(Protocol):
    def get(self, request: TransportRequest) -> TransportResponse:
        """Return bounded bytes and the time those bytes were observed."""


@runtime_checkable
class MetadataProvider(Protocol):
    @property
    def provider_name(self) -> str:
        """Return the provider identifier used in observation envelopes."""

    @property
    def parser_version(self) -> str:
        """Return the adapter parser version used for compatibility checks."""

    def fetch(
        self,
        identifier: str | NormalizedRequestIdentity,
        *,
        refresh: bool = False,
    ) -> MetadataEnrichment:
        """Acquire or replay one immutable metadata observation."""


class HttpsMetadataTransport:
    """Small HTTPS transport; tests inject a deterministic fake instead."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def get(self, request: TransportRequest) -> TransportResponse:
        with urlopen(  # noqa: S310 - adapter supplies a fixed HTTPS origin
            Request(request.url, headers=dict(request.headers)),
            timeout=request.timeout_seconds,
        ) as response:
            body = response.read(request.max_response_bytes + 1)
        if len(body) > request.max_response_bytes:
            raise ProviderResponseError(
                "provider response exceeds its byte limit"
            )
        return TransportResponse(
            body=body, retrieved_at=self._clock().isoformat()
        )


class CrossrefClient:
    provider_name = "crossref"
    parser_version = CROSSREF_PARSER_VERSION

    def __init__(
        self,
        *,
        mailto: str | None = None,
        cache_directory: Path | None = None,
        timeout_seconds: float = 20.0,
        transport: MetadataTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self.mailto = mailto
        self.cache_directory = cache_directory
        self.timeout_seconds = timeout_seconds
        self.transport = transport or HttpsMetadataTransport()
        self._cache_root: AuthorizedRoot | None = None
        if cache_directory is not None:
            root = AuthorizedRoot.create(
                cache_directory,
                label="provider cache root",
            )
            state = root.state("crossref")
            if state == "missing":
                self._cache_root = root.create_directory("crossref")
            elif state == "directory":
                self._cache_root = AuthorizedRoot.existing(
                    root.child_path("crossref"),
                    label="Crossref cache root",
                )
            else:
                raise ProviderCacheError(
                    "Crossref cache path is not a directory"
                )

    def fetch(
        self,
        identifier: str | NormalizedRequestIdentity,
        *,
        refresh: bool = False,
    ) -> MetadataEnrichment:
        request_identity = self.normalize_identifier(identifier)
        if not refresh:
            cached = self._load_latest(request_identity)
            if cached is not None:
                return cached
        return self._acquire(request_identity)

    @staticmethod
    def normalize_identifier(
        identifier: str | NormalizedRequestIdentity,
    ) -> NormalizedRequestIdentity:
        if isinstance(identifier, NormalizedRequestIdentity):
            if identifier.scheme != "doi":
                raise ProviderError("Crossref requires a DOI request identity")
            if normalize_doi(identifier.value) != identifier.value:
                raise ProviderError("Crossref requires a normalized DOI value")
            return identifier
        return normalize_persistent_identifier("doi", identifier)

    def _acquire(
        self,
        request_identity: NormalizedRequestIdentity,
    ) -> MetadataEnrichment:
        source_url = _crossref_url(request_identity)
        request = TransportRequest(
            url=source_url,
            headers=(("User-Agent", self._user_agent()),),
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=MAX_RESPONSE_BYTES,
        )
        response = self.transport.get(request)
        if not isinstance(response.body, bytes):
            raise ProviderResponseError("transport response body must be bytes")
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise ProviderResponseError(
                "provider response exceeds its byte limit"
            )
        _parse_timestamp(response.retrieved_at)
        cache_status = (
            CacheStatus.PUBLISHED
            if self._cache_root is not None
            else CacheStatus.DISABLED
        )
        observation = ResponseObservationEnvelope(
            schema_version=CACHE_SCHEMA_VERSION,
            request_identity=request_identity,
            provider=self.provider_name,
            retrieved_at=response.retrieved_at,
            source_url=source_url,
            response_sha256=hashlib.sha256(response.body).hexdigest(),
            response_bytes=len(response.body),
            parser_version=self.parser_version,
            generator_version=OBSERVATION_GENERATOR_VERSION,
            cache_status=cache_status,
        )
        result = self._parse_response(
            request_identity,
            response.body,
            observation,
            delivery_status=DeliveryStatus.PROVIDER_RESPONSE,
        )
        if self._cache_root is not None:
            self._publish(observation, response.body)
        return result

    def _load_latest(
        self,
        request_identity: NormalizedRequestIdentity,
    ) -> MetadataEnrichment | None:
        if self._cache_root is None:
            return None
        request_digest = _request_digest(request_identity)
        prefix = f"v1-{request_digest}-"
        try:
            names = self._cache_root.iter_files(
                suffix=".json",
                recursive=False,
                reject_directories=True,
            )
        except PathSafetyError as error:
            raise ProviderCacheError("provider cache is unsafe") from error
        matches = [item for item in names if item.name.startswith(prefix)]
        loaded: list[tuple[ResponseObservationEnvelope, bytes]] = []
        for name in matches:
            loaded.append(self._load_entry(name.name, request_identity))
        if not loaded:
            return None
        latest_time = max(
            _parse_timestamp(item[0].retrieved_at) for item in loaded
        )
        latest = [
            item
            for item in loaded
            if _parse_timestamp(item[0].retrieved_at) == latest_time
        ]
        if len(latest) != 1:
            raise ProviderCacheConflictError(
                "cache has multiple observations at the latest retrieval time"
            )
        observation, body = latest[0]
        return self._parse_response(
            request_identity,
            body,
            observation,
            delivery_status=DeliveryStatus.CACHE_REPLAY,
        )

    def _publish(
        self,
        observation: ResponseObservationEnvelope,
        body: bytes,
    ) -> None:
        if self._cache_root is None:
            raise AssertionError("cache publication requires a cache root")
        content = _cache_entry_bytes(observation, body)
        request_digest = _request_digest(observation.request_identity)
        content_digest = hashlib.sha256(content).hexdigest()
        name = f"v1-{request_digest}-{content_digest}.json"
        try:
            self._cache_root.write_bytes(name, content, replace=False)
        except FileExistsError:
            try:
                existing = self._cache_root.read_bytes(
                    name,
                    max_bytes=MAX_CACHE_BYTES,
                )
            except (OSError, UnicodeError, PathSafetyError) as error:
                raise ProviderCacheError(
                    "existing cache entry cannot be safely verified"
                ) from error
            if existing != content:
                raise ProviderCacheConflictError(
                    "existing cache entry differs; refusing overwrite"
                ) from None

    def _load_entry(
        self,
        name: str,
        expected_request: NormalizedRequestIdentity,
    ) -> tuple[ResponseObservationEnvelope, bytes]:
        if self._cache_root is None:
            raise AssertionError("cache loading requires a cache root")
        name_match = _CACHE_NAME.fullmatch(name)
        if name_match is None:
            raise ProviderCacheError("matching cache filename is malformed")
        if name_match.group(1) != _request_digest(expected_request):
            raise ProviderCacheError(
                "cache filename request identity conflicts"
            )
        try:
            content = self._cache_root.read_bytes(
                name, max_bytes=MAX_CACHE_BYTES
            )
        except (OSError, UnicodeError, PathSafetyError) as error:
            raise ProviderCacheError(
                "cache entry cannot be safely read"
            ) from error
        if hashlib.sha256(content).hexdigest() != name_match.group(2):
            raise ProviderCacheConflictError(
                "cache filename content hash conflicts"
            )
        data = _decode_json_object(content, source="cache entry")
        if set(data) != {"schema_version", "observation", "response_base64"}:
            raise ProviderCacheError(
                "cache entry fields are incomplete or unknown"
            )
        if type(data["schema_version"]) is not int:
            raise ProviderCacheError("cache schema version must be an integer")
        if data["schema_version"] != CACHE_SCHEMA_VERSION:
            raise ProviderCacheError("cache schema version is incompatible")
        observation_data = data["observation"]
        if not isinstance(observation_data, dict):
            raise ProviderCacheError("cache observation must be an object")
        observation = _observation_from_mapping(observation_data)
        if observation.request_identity != expected_request:
            raise ProviderCacheConflictError(
                "cached request identity conflicts"
            )
        if observation.provider != self.provider_name:
            raise ProviderCacheError("cached provider is incompatible")
        if observation.parser_version != self.parser_version:
            raise ProviderCacheError("cached parser version is incompatible")
        if observation.generator_version != OBSERVATION_GENERATOR_VERSION:
            raise ProviderCacheError("cached generator version is incompatible")
        if observation.source_url != _crossref_url(expected_request):
            raise ProviderCacheConflictError("cached source URL conflicts")
        if observation.cache_status != CacheStatus.PUBLISHED:
            raise ProviderCacheError(
                "cached observation has incompatible status"
            )
        encoded = data["response_base64"]
        if not isinstance(encoded, str):
            raise ProviderCacheError(
                "cached response bytes must be base64 text"
            )
        try:
            body = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ProviderCacheError(
                "cached response bytes are malformed"
            ) from error
        if len(body) != observation.response_bytes:
            raise ProviderCacheConflictError(
                "cached response byte size conflicts"
            )
        if hashlib.sha256(body).hexdigest() != observation.response_sha256:
            raise ProviderCacheConflictError("cached response hash conflicts")
        return observation, body

    def _parse_response(
        self,
        request_identity: NormalizedRequestIdentity,
        body: bytes,
        observation: ResponseObservationEnvelope,
        *,
        delivery_status: DeliveryStatus,
    ) -> MetadataEnrichment:
        payload = _decode_json_object(body, source="Crossref response")
        status = payload.get("status")
        if not isinstance(status, str):
            raise ProviderResponseError(
                "Crossref response has no string success status"
            )
        if status != "ok":
            raise ProviderResponseError("Crossref response status is not ok")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseError(
                "Crossref response has no message object"
            )

        fields = tuple(
            _provider_field(message, name)
            for name in ("DOI", "title", "author", "issued", "abstract")
        )
        proposals: list[NormalizedFieldProposal] = []
        discrepancies: list[FieldDiscrepancy] = []

        raw_doi = message.get("DOI")
        if raw_doi is not None:
            if not isinstance(raw_doi, str):
                raise ProviderResponseError(
                    "Crossref DOI must be a string or null"
                )
            normalized_doi = normalize_doi(raw_doi)
            if normalized_doi is not None:
                proposal = NormalizedFieldProposal("doi", (normalized_doi,))
                proposals.append(proposal)
                if normalized_doi != request_identity.value:
                    discrepancies.append(
                        FieldDiscrepancy(
                            field="doi",
                            kind=DiscrepancyKind.REQUEST_PROVIDER_CONFLICT,
                            values=(
                                DiscrepantValue(
                                    "request",
                                    (request_identity.value,),
                                ),
                                DiscrepantValue("crossref", (normalized_doi,)),
                            ),
                        )
                    )

        if "title" in message and message["title"] is not None:
            raw_titles = message["title"]
            if (
                not isinstance(raw_titles, list)
                or len(raw_titles) > _MAX_TITLES
            ):
                raise ProviderResponseError(
                    "Crossref title list is malformed or oversized"
                )
            if any(not isinstance(value, str) for value in raw_titles):
                raise ProviderResponseError(
                    "Crossref title values must be strings"
                )
            titles = tuple(_normalize_text(value) for value in raw_titles)
            titles = tuple(value for value in titles if value)
            if titles:
                proposals.append(NormalizedFieldProposal("title", titles))

        if "author" in message and message["author"] is not None:
            raw_authors = message["author"]
            if (
                not isinstance(raw_authors, list)
                or len(raw_authors) > _MAX_AUTHORS
            ):
                raise ProviderResponseError(
                    "Crossref author list is malformed or oversized"
                )
            authors: list[str] = []
            for person in raw_authors:
                if not isinstance(person, dict):
                    raise ProviderResponseError(
                        "Crossref author must be an object"
                    )
                names: list[str] = []
                for part in ("given", "family"):
                    value = person.get(part)
                    if value is not None and not isinstance(value, str):
                        raise ProviderResponseError(
                            "Crossref author names must be strings or null"
                        )
                    if isinstance(value, str) and _normalize_text(value):
                        names.append(_normalize_text(value))
                name = " ".join(names)
                if name:
                    authors.append(name)
            if authors:
                proposals.append(
                    NormalizedFieldProposal("authors", tuple(authors))
                )

        if "issued" in message and message["issued"] is not None:
            raw_issued = message["issued"]
            if not isinstance(raw_issued, dict):
                raise ProviderResponseError(
                    "Crossref issued field must be an object"
                )
            date_parts = raw_issued.get("date-parts")
            if date_parts is not None:
                if (
                    not isinstance(date_parts, list)
                    or len(date_parts) > _MAX_DATE_PARTS
                    or any(not isinstance(part, list) for part in date_parts)
                    or any(
                        len(cast(list[object], part)) > _MAX_DATE_PARTS
                        for part in date_parts
                    )
                ):
                    raise ProviderResponseError(
                        "Crossref date parts are malformed or oversized"
                    )
                if date_parts and date_parts[0]:
                    year = date_parts[0][0]
                    if type(year) is not int or not 0 <= year <= 9999:
                        raise ProviderResponseError("Crossref year is invalid")
                    proposals.append(
                        NormalizedFieldProposal("year", (str(year),))
                    )

        if "abstract" in message and message["abstract"] is not None:
            raw_abstract = message["abstract"]
            if not isinstance(raw_abstract, str):
                raise ProviderResponseError(
                    "Crossref abstract must be a string or null"
                )
            abstract = _normalize_text(
                html.unescape(_TAG.sub(" ", raw_abstract))
            )
            if abstract:
                proposals.append(
                    NormalizedFieldProposal("abstract", (abstract,))
                )

        return MetadataEnrichment(
            observation=observation,
            delivery_status=delivery_status,
            provider_fields=fields,
            normalized_proposals=tuple(proposals),
            discrepancies=tuple(discrepancies),
        )

    def _user_agent(self) -> str:
        agent = "projectkoios-references/0.0.0"
        if self.mailto:
            return f"{agent} (mailto:{self.mailto})"
        return agent


def compare_provider_enrichments(
    *observations: MetadataEnrichment,
) -> tuple[FieldDiscrepancy, ...]:
    """Report conflicts without selecting or merging provider values."""
    by_field: dict[str, list[DiscrepantValue]] = {}
    for result in observations:
        source = f"{result.provider}:{result.observation.observation_id}"
        for proposal in result.normalized_proposals:
            by_field.setdefault(proposal.field, []).append(
                DiscrepantValue(source, proposal.values)
            )
    discrepancies: list[FieldDiscrepancy] = []
    for field, values in sorted(by_field.items()):
        distinct = {value.values for value in values}
        if len(distinct) > 1:
            discrepancies.append(
                FieldDiscrepancy(
                    field=field,
                    kind=DiscrepancyKind.PROVIDER_CONFLICT,
                    values=tuple(values),
                )
            )
    return tuple(discrepancies)


def _crossref_url(request: NormalizedRequestIdentity) -> str:
    return f"https://api.crossref.org/works/{quote(request.value, safe='')}"


def _request_digest(request: NormalizedRequestIdentity) -> str:
    return hashlib.sha256(request.canonical.encode("utf-8")).hexdigest()


def _provider_field(message: dict[str, object], name: str) -> ProviderField:
    if name not in message:
        return ProviderField(name=name, present=False, value_json=None)
    return ProviderField(
        name=name,
        present=True,
        value_json=json.dumps(
            message[name],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _validate_https_source_url(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_URL_LENGTH
        or "\\" in value
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise ProviderCacheError("observation source URL is malformed")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ProviderCacheError(
            "observation source URL is malformed"
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or _SAFE_HOST.fullmatch(parsed.hostname) is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ProviderCacheError(
            "observation source URL must be credential-free HTTPS "
            "without a fragment"
        )


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ProviderCacheError("retrieval time must be bounded ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ProviderCacheError("retrieval time is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderCacheError("retrieval time must include a UTC offset")
    return parsed.astimezone(UTC)


class _DuplicateJsonKeyError(ValueError):
    pass


class _NonStandardJsonConstantError(ValueError):
    pass


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(
                f"JSON contains duplicate field: {key}"
            )
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> object:
    raise _NonStandardJsonConstantError(
        f"JSON contains non-standard constant: {value}"
    )


def _decode_json_object(content: bytes, *, source: str) -> dict[str, object]:
    if len(content) > MAX_RESPONSE_BYTES and source == "Crossref response":
        raise ProviderResponseError("Crossref response exceeds its byte limit")
    try:
        decoded = content.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateJsonKeyError,
        _NonStandardJsonConstantError,
    ) as error:
        error_type = (
            ProviderCacheError
            if source == "cache entry"
            else ProviderResponseError
        )
        raise error_type(f"{source} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        error_type = (
            ProviderCacheError
            if source == "cache entry"
            else ProviderResponseError
        )
        raise error_type(f"{source} must be a JSON object")
    return value


def _observation_to_mapping(
    observation: ResponseObservationEnvelope,
) -> dict[str, object]:
    return {
        "schema_version": observation.schema_version,
        "request_identity": {
            "scheme": observation.request_identity.scheme,
            "value": observation.request_identity.value,
        },
        "provider": observation.provider,
        "retrieved_at": observation.retrieved_at,
        "source_url": observation.source_url,
        "response_sha256": observation.response_sha256,
        "response_bytes": observation.response_bytes,
        "parser_version": observation.parser_version,
        "generator_version": observation.generator_version,
        "cache_status": observation.cache_status.value,
    }


def _observation_from_mapping(
    data: dict[str, object],
) -> ResponseObservationEnvelope:
    expected = {
        "schema_version",
        "request_identity",
        "provider",
        "retrieved_at",
        "source_url",
        "response_sha256",
        "response_bytes",
        "parser_version",
        "generator_version",
        "cache_status",
    }
    if set(data) != expected:
        raise ProviderCacheError(
            "cache observation fields are incomplete or unknown"
        )
    request_data = data["request_identity"]
    if not isinstance(request_data, dict) or set(request_data) != {
        "scheme",
        "value",
    }:
        raise ProviderCacheError("cached request identity is malformed")
    scalar_types = {
        "schema_version": int,
        "provider": str,
        "retrieved_at": str,
        "source_url": str,
        "response_sha256": str,
        "response_bytes": int,
        "parser_version": str,
        "generator_version": str,
        "cache_status": str,
    }
    if any(
        type(data[name]) is not expected
        for name, expected in scalar_types.items()
    ):
        raise ProviderCacheError(
            "cached observation scalar types are malformed"
        )
    if any(
        not isinstance(request_data[name], str) for name in ("scheme", "value")
    ):
        raise ProviderCacheError("cached request identity types are malformed")
    try:
        request = NormalizedRequestIdentity(
            scheme=cast(str, request_data["scheme"]),
            value=cast(str, request_data["value"]),
        )
        cache_status = CacheStatus(cast(str, data["cache_status"]))
        return ResponseObservationEnvelope(
            schema_version=cast(int, data["schema_version"]),
            request_identity=request,
            provider=cast(str, data["provider"]),
            retrieved_at=cast(str, data["retrieved_at"]),
            source_url=cast(str, data["source_url"]),
            response_sha256=cast(str, data["response_sha256"]),
            response_bytes=cast(int, data["response_bytes"]),
            parser_version=cast(str, data["parser_version"]),
            generator_version=cast(str, data["generator_version"]),
            cache_status=cache_status,
        )
    except (TypeError, ValueError) as error:
        raise ProviderCacheError("cached observation is malformed") from error


def _cache_entry_bytes(
    observation: ResponseObservationEnvelope,
    body: bytes,
) -> bytes:
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderResponseError("provider response exceeds its byte limit")
    data = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "observation": _observation_to_mapping(observation),
        "response_base64": base64.b64encode(body).decode("ascii"),
    }
    rendered = _canonical_json_bytes(data) + b"\n"
    if len(rendered) > MAX_CACHE_BYTES:
        raise ProviderCacheError("rendered cache entry exceeds its byte limit")
    return rendered


def _canonical_json_bytes(data: object) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
