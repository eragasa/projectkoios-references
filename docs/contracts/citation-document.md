# Citation target and bibliography contracts

## Status and durability boundary

This document defines canonical in-memory prototype records owned by
`projectkoios-references`. They have no numbered wire schema, loader, writer, or
separately promised persistence compatibility. Git retains prototype history; a
durable version begins only after an explicit external or irreplaceable
boundary is approved.

## Scope

References accepts a bounded neutral view of one complete citation snapshot
supplied by a target owner. It does not read or parse target files. The view
preserves every literal-key occurrence, exact target bibliography entry,
target-owned source gap, source-relative locator, and content identity.

A separate exact binding may connect a target bibliography entry to one
`SourceBibliographyObservation` owned by References. Neither package defines
document discovery, availability, processing, receipt, target-association,
accepted-reference identity, rights, review, ingestion, scientific-support, or
publication state.

## Neutral target snapshot

Canonical citation inventory records live in
`projectkoios.references.citations`. The snapshot is complete-or-absent; it has
no incomplete success form. Malformed, partial, over-limit, or internally
inconsistent input is rejected.

The snapshot retains:

- the opaque target `snapshot_id`;
- exact bibliography path and content identity;
- ordered occurrence records with literal key, source locator, exact origin
  (`direct`, `eqincite_expansion`, or `citation_todo_expansion`), and target
  indexes;
- lexically ordered groups that partition every occurrence exactly once;
- source-ordered bibliography entries;
- explicit missing, duplicate, and uncited key sets; and
- target-owned source gaps without invented citation keys.

The live target adapter performs only two field renames:
`bibliography_entry_id` to `entry_id` and `bibliography_path` to
`bibliography_source_path`. Complete owner source-file, include, call, todo,
request, and result records remain target-owned and are represented by the
replay-validated opaque snapshot identity rather than copied.

Literal citation keys use the owner's exact ASCII grammar
`[A-Za-z0-9._-]{1,200}`. They are source data, not portable filenames. Source
locators use bounded, normalized, root-relative POSIX paths and do not inherit
Windows-reserved-name or portable filesystem mutation policy.

`target_projection_id` is a deterministic identity over the complete canonical
snapshot payload. It does not confer processing or acceptance authority. A
consumer associating another owner record to a citation group should retain the
exact `target_projection_id`, opaque `snapshot_id`, and `group_id`; the literal
key alone is not an identity.

## Exact bibliography observation binding

Canonical bibliography binding records live in
`projectkoios.references.bibliography`.

A target bibliography entry may carry a nullable
`source_bibliography_observation_id`. The target owner never fabricates that
identity. `CitationBibliographyObservationBinding` independently checks exact
agreement across:

- literal bibliography key and source-ordered entry index;
- normalized source path;
- bibliography digest and byte size;
- verbatim-entry digest and byte size; and
- a non-null owner-supplied observation identity.

The binding identity contains the exact target entry identity and References
observation identity. It does not resolve a canonical reference or authorize
document processing.

## Bounds and failure behavior

The implementation bounds occurrences, unique keys, bibliography entries,
source gaps, identifiers, normalized relative POSIX source paths, source-file
counts, aggregate source bytes, and canonical identity payload bytes.
Per-record target references are limited to 256; target records and source-file
counts are bounded at 10,000; one target source and aggregate target source
bytes are bounded at 100,000,000; and canonical identity payloads are bounded
at 20,000,000 UTF-8 bytes.

Ordering drift, duplicate identities, inconsistent derived key sets, conflicting
source identities, malformed owner IDs, mismatched bibliography observations,
and replay drift fail closed. These checks establish exact evidence identity,
not permission to process, copy, publish, or admit content.
