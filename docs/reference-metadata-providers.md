# Reference metadata provider observations

`projectkoios.references.enrichment` defines the provider boundary used by
reference metadata acquisition. Version 1 provides Crossref conformance only.
OpenAlex, citation discovery, rate-limit policy, canonical catalog mutation, and
metadata acceptance are deliberately outside this milestone.

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

## Immutable observation envelope

Every result has a frozen, provider-neutral `ResponseObservationEnvelope`
containing:

- schema version;
- normalized request scheme and value;
- provider;
- original retrieval time with a UTC offset;
- source URL;
- exact response byte length and SHA-256 digest;
- parser and observation-generator versions; and
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

Crossref observations use content-addressed files beneath the explicitly
configured cache root. A request may retain multiple observations. Refreshing a
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

Current bounds are 2,000,000 provider-response bytes and 3,000,000 serialized
cache bytes, with additional list and field limits in the Crossref parser. A
Crossref response must explicitly report `status: "ok"` before its `message` can
be interpreted; failed or partial responses cannot become metadata absence.
Unknown Crossref response fields remain preserved in the exact response bytes
and do not prevent parsing known fields. Unknown cache-envelope fields are
rejected because cache interpretation must be versioned explicitly.

Deeper parser-nesting and decompression-wide resource policy remains deferred to
REF-METADATA parser-hardening issue #24. The current byte, item, and field bounds
remain enforced until that policy is defined.

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
