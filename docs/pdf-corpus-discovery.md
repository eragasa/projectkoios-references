# Generic PDF corpus discovery

## Status and authority boundary

The Python library implements the Proposed
`projectkoios.references.pdf-corpus-discovery@0.1.0` contract. It is a
bibliography-independent, read-only inventory of explicitly authorized roots.
There is no references CLI for this contract yet.

Discovery identifies extension candidates, records exact byte identities when
byte access is safe, and distinguishes a valid `%PDF-` prefix from a `.pdf`
name whose bytes do not have that prefix. It does not resolve document content,
match a bibliography, establish relevance or canonical identity, grant rights,
verify scientific claims, hydrate a provider object, or authorize ingestion.
Applications and ingestion policy own those later decisions.

## Explicit roots and runtime-only paths

Callers construct one `PdfCorpusRoot` for each authorized root:

```python
from pathlib import Path

from projectkoios.references import (
    MacOSFileProviderPlaceholderProbe,
    PdfCorpusRoot,
    RootStorageClass,
    discover_pdf_corpus,
)

local = Path("/authorized/local/papers")
icloud = Path("/authorized/iCloud/papers")
plan = discover_pdf_corpus(
    (
        PdfCorpusRoot("local-papers", local, RootStorageClass.LOCAL),
        PdfCorpusRoot(
            "icloud-papers",
            icloud,
            RootStorageClass.CLOUD_BACKED,
            MacOSFileProviderPlaceholderProbe(icloud),
        ),
    )
)
```

The absolute `Path` values are runtime authorization inputs. Canonical plan
JSON stores only root aliases, declared storage classes, probe evidence, and
normalized relative paths. It never stores an absolute root.

`discover_pdf_corpus` rejects duplicate, ancestor/descendant, or otherwise
overlapping declared roots using normalized lexical paths before any root path
is touched. After metadata-only binding, it checks resolved root paths again
before inventory, covering overlap hidden behind parent symlinks. This applies
to all storage-class combinations. A nested provider or mounted corpus must be
supplied as a separate, non-overlapping operation rather than reached through a
broader root.

Discovery recursively inventories case-insensitive `.pdf` extensions in
deterministic alias/path order. Traversal uses no-follow directory descriptors.
Symlinks are observations and are never traversed. Every opened parent
directory and candidate leaf is checked against the authorized root device.
A differing device is retained as a typed `filesystem-boundary` skip and is not
descended or read, including a mounted leaf or a directory replaced after name
inventory. Rebinding performs the same checks and fails rather than crossing
the boundary. Special objects, nonportable names, inaccessible directories,
unreadable files, missing or changed objects,
cloud placeholders, unsupported or ambiguous provider states, and
entry/file/depth/byte limits remain typed `PdfSkippedObservation` values. Any
skip makes `coverage_status` equal `incomplete`; incomplete never means that an
unobserved PDF is absent.

## Exact sources and replay

An ordinary regular file produces one `PdfSourceObservation` containing:

- root alias, relative path, declared storage class, and probe identity;
- exact streaming SHA-256 and byte size;
- `blob:sha256:...` content identity;
- a canonical `pdf-source-observation:sha256:...` identity; and
- `pdf_header_valid`, which is true only for an exact `%PDF-` prefix.

A `.pdf` extension candidate with an invalid header remains an exact source
observation; it does not abort the corpus. It is excluded from
`plan.processable_sources`. Applications should consume only that filtered
view.

`PdfCorpusDiscoveryPlan.to_json()` emits one canonical strict JSON form,
`PdfCorpusDiscoveryPlan.from_json()` rejects unknown, malformed, over-limit,
tampered, or noncanonical input, and `plan.plan_id` identifies the entire
canonical plan. Source and skipped relative paths are checked against the
recorded path-text and traversal-depth limits, in addition to file, total-byte,
count, JSON, and identity checks. The plan records the complete effective I/O
profile and its content identity.

Before processing or copying bytes, an application can call
`rebind_pdf_source(source, roots)`. Rebinding resolves the alias against newly
supplied explicit runtime roots, enforces the caller's active path-text,
traversal-depth, per-file, and total-byte limits before reopening, then rechecks
cloud metadata preflight, root/leaf device, PDF header, size, and SHA-256. The
byte observation uses the smaller of the active per-file and total-byte limits
and returns a runtime-only `ReboundPdfSource`. Its
`AuthorizedRoot` and `PurePosixPath` can be passed to the existing
`AuthorizedRoot.copy_file_from` descriptor-confined copy primitive. Rebinding
never hydrates or copies by itself.

## macOS File Provider/iCloud metadata probe

`MacOSFileProviderPlaceholderProbe` is the only production cloud probe in this
repository. It is explicitly injected per root; storage class and provider
semantics are never inferred from a path. The probe is supported only on macOS
when Python exposes `stat.SF_DATALESS`.

The probe opens directory descriptors only and obtains candidate leaf metadata
with `os.stat(..., follow_symlinks=False)`. It never opens or reads a candidate
file. A regular file carrying `SF_DATALESS` is `cloud-placeholder`. A regular,
readable file with available `st_flags` and no `SF_DATALESS` is
`ordinary-file`. Missing, access-controlled, and mode-unreadable states remain
typed; symlinks, nonregular objects, absent flag metadata, metadata errors, and
other uncertain states are `ambiguous`.

The concrete probe captures one normalized runtime root. `AuthorizedRoot`
rejects a different declared path, binds the probe to the same root
device/inode, and makes every later probe observation recheck that root
identity. Intermediate parent and candidate-leaf metadata must also remain on
the bound device. Generic injected probes remain caller-attested under the
`CloudPlaceholderProbe` protocol.

Metadata preflight and the later descriptor open/read are necessarily separate
system calls. A provider or concurrent actor can change state between them.
The implementation preflights again immediately before byte access, checks
bound root and open-leaf identity, and turns detected replacement or change
into an incomplete observation or rebind failure. It cannot make provider
metadata and byte opening one atomic operation. Operators must treat this
TOCTOU limitation as residual risk and use a separately authorized local export
when provider semantics cannot be trusted.

There are no Dropbox, Google Drive, OneDrive, or provider account APIs. The
package opens no network connection, launches no external process or model,
and performs no explicit provider hydration or cloud mutation. Filesystem
metadata enumeration can cause OS/File Provider activity, including activity
the package cannot observe or control; an explicitly authorized cloud root and
supported metadata probe therefore remain required. The default for a
cloud-backed root without an explicit supported probe is
`unsupported-platform`.
