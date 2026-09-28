# Cloud-placeholder safety

## Status and activation condition

`REF-CLOUD-SAFETY-01` defines a provider-neutral, fail-closed preflight
boundary. It does not authorize a cloud-backed root, hydrate or download an
object, or implement Dropbox, Google Drive, OneDrive, account, credential,
network, or provider API behavior.

The repository provides one explicitly injected production adapter:
`MacOSFileProviderPlaceholderProbe`. On macOS with `stat.SF_DATALESS`, it uses
only no-follow stat metadata and directory descriptors to classify a regular
File Provider/iCloud object. It never opens candidate bytes. There is no
automatic adapter selection: the default capability for a root declared
`cloud-backed` without an injected supported probe remains
`unsupported-platform`. Such a root is rejected by existing single-file APIs
or retained as incomplete by generic corpus discovery before its filesystem
path is opened or inventoried; it cannot produce empty, missing, or complete
coverage. See [generic PDF corpus discovery](pdf-corpus-discovery.md)
for the library-only corpus API.

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

The default probe reports `unsupported-platform`. Generic probe tests use only
synthetic temporary fixtures. Production-probe tests also use only temporary
synthetic files and injected stat metadata; they do not scan user roots or use
live cloud fixtures. The package uses no provider credentials or account API,
opens no network connection, launches no external process, and makes no
explicit hydration call. OS/File Provider activity caused by filesystem
metadata enumeration is outside package visibility and control.

Unsupported or ambiguous evidence does not become absence or complete
coverage. Existing fail-closed single-file APIs raise
`PlaceholderPreflightError`; generic corpus discovery retains the state as a
typed skipped observation in an `incomplete` canonical plan. A known
placeholder is represented by root alias, normalized relative path, declared
storage class, probe identity, and typed status. Absolute paths are excluded.
Hashing, PDF-header reads, verification, reconciliation, validation reads,
rebind, and materialization recheck preflight before opening candidate bytes. A
placeholder, inaccessible file, or other non-ordinary observation cannot
produce complete evidence. Typed diagnostics and plan JSON are privacy reduced.
All generic mutation methods reject cloud-backed destinations even when an
injected probe reports supported. Materialization remains a separate explicit
local-destination operation and never requests placeholder hydration.

Generic corpus discovery also rejects duplicate or overlapping roots before
traversal and rechecks resolved paths after metadata binding. It does not cross
a child-directory device boundary under the parent root's storage declaration;
the boundary is retained as an incomplete skip and must be handled as a
separately classified, non-overlapping operation.

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

## macOS probe scope and state changes

The macOS probe captures one normalized root path. Binding rejects a different
runtime root and binds the probe to the same device/inode used by
`AuthorizedRoot`; each observation rechecks that identity. `SF_DATALESS` is
`cloud-placeholder`. A readable regular file with available flags and no
`SF_DATALESS` may be `ordinary-file`; uncertain metadata is `ambiguous`.

Metadata preflight and byte opening are separate system calls. The implementation
rechecks immediately before access and detects bound-root, open-leaf, size,
hash, and metadata changes where possible, but cannot make provider metadata
and byte access atomic. A concurrent/provider state transition is residual
TOCTOU risk and fails closed when detected. Use a separately authorized local
export when that provider risk is unacceptable.
