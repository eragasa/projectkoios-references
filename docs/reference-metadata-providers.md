# Reference metadata provider observations

`projectkoios.references.enrichment` defines the identifier-enrichment provider
boundary, and `projectkoios.references.openalex` defines the owner-native works-
search boundary. Crossref provides DOI enrichment with optional immutable cache
replay. OpenAlex provides one bounded, read-only basic-page search observation.
Citation discovery beyond the returned page, retry policy, canonical catalog
mutation, and metadata acceptance remain outside this milestone.

## Provider and transport protocols

`MetadataProvider` accepts a scheme-qualified `NormalizedRequestIdentity` (or a
DOI string for the Crossref convenience API) and returns a
`MetadataEnrichment`. `MetadataTransport` is injected into `CrossrefClient` so
provider parsing and cache behavior can be tested using deterministic response
bytes and retrieval times. The default HTTPS transport performs one bounded
read from the fixed Crossref API origin. Tests never use it.

Persistent identifiers are normalized by an explicitly named scheme before a
request URL or cache identity is made. The provider-neutral identity envelope
accepts bounded normalized scheme/value pairs. Crossref version 1 implements DOI
normalization and fails closed for unsupported input schemes; it does not guess
that an unlabelled arXiv, ISBN, or other identifier is a DOI.

## OpenAlex works search

`OpenAlexWorksProvider` accepts an immutable `OpenAlexWorksSearchRequest` and
returns an immutable `OpenAlexWorksSearchResult`. Queries are stripped, nonempty,
control-free text of at most 500 characters. `page` is 1 through 10,000,
`per_page` is 1 through 100, and `page * per_page` may not exceed OpenAlex's
10,000-result basic-paging boundary. This slice does not use cursor paging.
Anonymous first-page requests are supported. An optional caller-supplied API key
is sent only as a bearer credential; it is absent from request URLs, object
representations, observation identity, result fields, and exception messages.
The package does not request or create a key.

The adapter always sends one GET to `https://api.openalex.org/works` and selects
only `id`, `title`, `publication_year`, `type`, `doi`, `authorships`,
`primary_location`, and `cited_by_count`. It returns the OpenAlex work ID, title,
publication year, work type, provider DOI text, up to 1,024 ordered author display
names, primary-source display name, cited-by count, and a landing URL. Total and
cited-by counts share the exported `OPENALEX_MAX_COUNT = 1_000_000_000` HTTP/Web
boundary. When the primary location has no landing URL, the OpenAlex work ID URL
is the landing URL.
Provider strings are retained without HTML removal, whitespace normalization, or
trust promotion. They remain untrusted output that consumers must escape for
their output format.

The result also records total count, exact page and page-size echo, exact decimal
`cost_usd` when present, and credential-free retrieval provenance: normalized
request, retrieval time, source URL, response byte length and SHA-256, parser
version, and effective I/O-limit evidence. The parser requires strict UTF-8 JSON,
rejects duplicate keys and non-standard numbers, checks nesting before JSON
allocation, applies the effective `max_entries` to all JSON values and keys,
applies the effective `max_text_bytes` to their aggregate UTF-8 string bytes,
bounds response bytes and individual list cardinalities, requires an exact
selected-field set per work, and fails if provider paging differs from the
request. Redirects and responses using repository-unowned content encoding are
rejected. Malformed injected status, body, retrieval time, retry-after, or
content-encoding metadata is always an `OpenAlexProjectionError` before HTTP
status classification. `cost_usd` is either absent or an exact finite
nonnegative `Decimal` no greater than exported `OPENALEX_MAX_COST_USD =
Decimal("1000000")`, with at most exported
`OPENALEX_MAX_COST_DECIMAL_PLACES = 8`. The owner preflights exponent, digit
count, range, and exported `OPENALEX_MAX_COST_FIXED_CHARACTERS = 16` before
calling `format(value, "f")`, so exponent notation cannot expand unboundedly in
an HTTP consumer.

`OpenAlexProjectionError`, `OpenAlexUnavailableError`,
`OpenAlexUpstreamError`, and `OpenAlexRateLimitError` keep malformed projection,
transport failure, non-success HTTP status, and HTTP 429 distinct. The provider
does not retry. It has no cache path, filesystem or catalog dependency, mutation,
promotion, acceptance, or completeness claim. Tests inject a fake transport and
make no live provider request.

## Immutable Crossref observation envelope

Every result has a frozen, provider-neutral `ResponseObservationEnvelope`
containing:

- schema version;
- normalized request scheme and value;
- provider;
- original retrieval time with a UTC offset;
- source URL;
- exact response byte length and SHA-256 digest;
- parser and observation-generator versions;
- the effective response-byte ceiling and complete I/O-profile identity; and
- original cache-publication status.

The core envelope accepts bounded safe provider/parser identifiers and bounded,
credential-free HTTPS source URLs without fragments. Provider adapters apply
their stricter invariants. Crossref cache replay requires the exact Crossref
provider identifier, current Crossref parser and observation-generator versions,
and the request-derived Crossref URL.

The envelope's `cache_status` is immutable evidence about the original
observation: `cache-published` or `cache-disabled`. The result's separate
`delivery_status` says whether this call returned a new provider response or an
exact cache replay. A replay therefore does not fabricate or rewrite the
retrieval time, source URL, response identity, parser/generator versions, or
original cache status.

`ProviderField` records selected Crossref fields as provider-verbatim JSON and
records absence explicitly. `NormalizedFieldProposal` is separate and remains
non-authoritative. `FieldDiscrepancy` records a request/provider or
provider/provider conflict without selecting a winner. No proposal, discrepancy,
or provider result mutates accepted metadata.

A missing or null abstract creates no abstract proposal or text. HTML removal
and whitespace normalization happen only in a normalized proposal; the exact
provider abstract remains in the verbatim field and response bytes. No summary
or generated text can receive provider-abstract status.

## Bounded cache

Crossref schema-2 observations use `v2-` content-addressed files beneath the
explicitly configured cache root. A request-scoped legacy `v1-` entry is treated
as incompatible and blocks transport fallback rather than being ignored or
silently upgraded. A request may retain multiple observations. Refreshing a
changed response creates another file and never overwrites an earlier
observation. Normal replay chooses the uniquely latest original retrieval time;
an equal-time conflict fails closed rather than choosing implicitly.

Publication is atomic create-or-identical. An already existing destination is
accepted only when its bytes are identical. Cache reads enforce byte limits,
strict UTF-8 JSON (including rejection of duplicate keys and non-standard
`NaN`/infinity constants), exact known fields, the supported schema, parser and
generator versions, normalized request identity, source/provider compatibility,
base64 validity, byte length, response hash, and content-addressed filename.
Malformed, partial, oversized, incompatible, conflicting, symlinked, or
otherwise unsafe entries are not repaired or overwritten.

Crossref bounds are 2,000,000 provider-response bytes, 3,000,000 serialized
cache bytes, 1,000 cache files, 2,000 cache-directory entries, 500,000,000
serialized cache bytes per request replay, and JSON depth 64, with additional
list and field limits in the Crossref parser. OpenAlex search separately bounds
responses and JSON at 2,000,000 bytes, JSON depth at 16, results at 100, authors
per work at 1,024, every JSON list at 4,096, aggregate JSON string text at
512,000 bytes, total JSON values and keys at 100,000, and decimal cost fixed-point
rendering at 16 characters with at most 8 decimal places.
The effective profile is content-identified in every observation; incompatible
replay or caller limits fail closed. A Crossref response must explicitly report
`status: "ok"` before its `message` can
be interpreted; failed or partial responses cannot become metadata absence.
Unknown Crossref response fields remain preserved in the exact response bytes
and do not prevent parsing known fields. Unknown cache-envelope fields are
rejected because cache interpretation must be versioned explicitly.

Both HTTPS transports read at most one byte beyond the response ceiling. JSON
nesting is checked before parser allocation, and Crossref directory cardinality
is checked before sorting. Neither provider accepts content encoding that
requires a repository-owned decompression step; any future compressed transport
requires a separately bounded decompression policy.

## Status vocabulary

- `provider-response`: this call used newly observed transport bytes.
- `cache-replay`: this call replayed a validated immutable observation.
- `cache-published`: the original observation was atomically published.
- `cache-disabled`: the original observation was made without a cache.
- `request-provider-conflict`: the provider DOI differs from the normalized
  request DOI.
- `provider-conflict`: two normalized provider observations disagree; neither is
  selected automatically.

These statuses are technical provenance only. They do not mean that metadata is
accepted, canonical, scientifically verified, suitable for manuscript use, or
approved for publication.
