# Cloud-placeholder safety

## Status and activation condition

`REF-CLOUD-SAFETY-01` defines a provider-neutral, fail-closed preflight
boundary. It does not authorize a real cloud-backed root, hydrate or download
an object, or implement Dropbox, Google Drive, iCloud Drive, OneDrive, operating
system, or provider-specific behavior.

This safety boundary is blocking before any cloud-backed root is authorized.
The repository currently has no native or provider adapter, so the default
capability for every root declared `cloud-backed` is
`unsupported-platform`. Such a root is rejected before its filesystem path is
opened or inventoried and cannot produce empty, missing, or complete coverage.

## Explicit root declarations

Inventory and source-root APIs require `RootStorageClass`; there is no default.
Repeatable CLI roots use:

```text
local:ALIAS=/path/to/local/root
cloud-backed:ALIAS=/path/to/mixed-or-streaming/root
```

Bare legacy `ALIAS=PATH` input is rejected as unclassified. Every standalone
input or output path has a required sibling `--*-storage-class
local|cloud-backed` flag. Optional and repeatable keyed paths require matching
storage declarations before any path is touched. Paths and provider names are
never inspected to infer a storage class.

A local declaration means the operator has authorized the root as containing
ordinary local filesystem objects for this operation. It is not a probe result
and must not be used for a mixed or streaming provider root.

## Portable preflight model

The injected `CloudPlaceholderProbe` interface reports a bounded capability
identity and metadata-only candidate states:

- `ordinary-file`;
- `cloud-placeholder`;
- `missing`;
- `access-controlled`;
- `unreadable`;
- `unsupported-platform`; or
- `ambiguous`.

The default probe reports `unsupported-platform`. Tests use only synthetic,
injected probes. There are no native calls, provider credentials, account
access, network requests, or live cloud fixtures.

Unsupported or ambiguous evidence raises `PlaceholderPreflightError` and does
not become absence or complete coverage. A known placeholder is represented by
root alias, normalized relative path, declared storage class, probe identity,
and typed status. Absolute paths are excluded. Hashing, PDF-header reads,
verification, reconciliation, validation reads, and materialization recheck the
preflight before opening candidate bytes. A placeholder, inaccessible file, or other non-ordinary observation makes
asset discovery, managed-PDF scanning, and validation explicitly `incomplete`;
it cannot produce or replay complete evidence. The typed diagnostic has a
stable code and privacy-reduced JSON.
All generic mutation methods reject cloud-backed destinations even when an
injected probe reports supported. Materialization remains a separate explicit
local-destination operation and never hydrates a placeholder.

## Safe operational path

Hydration is outside default reference discovery and outside this issue. If an
operator separately authorizes a provider export, hydration, or copy, that
operation occurs outside `projectkoios-references` and writes into a separately
authorized, ordinary local staging root. The references commands then receive
that staging root explicitly as `local` and can inventory, hash, verify, or
materialize its local bytes.

That workflow does not make the external hydration evidence part of a scan,
does not grant rights or canonical identity, and does not turn a cloud root into
a local root by relabeling it.
