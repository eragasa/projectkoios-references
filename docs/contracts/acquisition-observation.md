# Acquisition observation contract

## Contract metadata

| Field | Value |
|---|---|
| Contract ID | `projectkoios.references.acquisition-observation` |
| Target version | `0.1.0` |
| Status | Proposed |
| Owner | `projectkoios-references` |
| Task | `REF-ACQUISITION-01` |
| Acceptance authority | Project Koios operator after owner and materially affected consumer review |
| Effective baseline | None while Proposed |

This document defines the Proposed acquisition-observation contract implemented
by acquisition-manifest schema version 4. It does not accept the contract.

## Scope and authority

An acquisition manifest records a bounded observation of bytes already held in
an explicitly authorized root. It does not retrieve content, bypass access
controls, verify a rights assertion, accept a canonical citation key, select a
manuscript citation, or authorize redistribution.

Each entry fixes all three authority safeguards:

- `identity_status: unaccepted-candidate`;
- `citekey_status: proposed-noncanonical`; and
- `manuscript_status: not-assessed`.

Acquisition, access, and rights are separate typed observations. Their status
values originate in normalized operator input. `basis: operator-assertion`
means the tool retained an assertion; it does not mean the assertion was
independently verified. When the optional acquisition status is absent, the
manifest records `not-assessed` with `basis: explicitly-not-assessed`.

## Identity and replay

A schema-version-4 manifest contains:

- contract, artifact, and generator identities;
- a content-derived `normalized_input_id` covering normalized semantic input;
- root storage and placeholder-probe preflight evidence;
- the complete effective I/O-limit profile and its content identity;
- every observed source as a root alias, traversal-free relative path, byte
  length, and SHA-256 digest;
- typed acquisition, access, and rights observations; and
- a content-derived `manifest_id` covering every field except itself.

Rows are sorted by proposed citekey and logical source locator before identity
and serialization. Canonical JSON replay is byte-identical. Parsing rejects
unknown, missing, noncanonical, or identity-conflicting content.

The normalized-input identity intentionally excludes the observed byte digest
and length. Thus a source-byte change retains the same normalized-input
identity but produces a different manifest identity. A metadata or status
change changes both identities.

## Bounded verification and publication

Creation and verification stream each source through descriptor-confined,
no-follow access. The operation enforces per-file, aggregate, row, CSV, JSON,
text, and nesting bounds. Cloud-backed roots require a supported injected
metadata-only placeholder probe and an ordinary-file result before bytes are
opened. Missing, unreadable, ambiguous, placeholder, replaced-root, symlink,
changed-during-read, oversized, and non-PDF inputs fail closed.

Publication is create-once and atomic within the destination directory. An
existing byte-identical manifest returns `unchanged`. An existing different,
truncated, oversized, nonregular, or symlink output is not overwritten or
repaired. Cloud-backed output mutation remains forbidden.

## Consumer projection

`AcquisitionManifest.projections()` returns immutable
`AcquisitionProjection` values. A projection carries the contract, manifest,
normalized-input, source-content, candidate-authority, acquisition, access, and
rights identities without exposing an absolute machine path. Reconciliation or
other projections may consume these observations as evidence, but must not
promote them into rights verification, canonical identity, manuscript
acceptance, or publication authority.

## Input columns

Required CSV columns are `proposed_citekey`, `root_alias`, `relative_path`,
`access_status`, `rights_status`, and `identity_status`. The optional columns
are `acquisition_status`, `doi`, `source_url`, and `source_version`.
`asset_status` remains a compatibility alias for `access_status`; if both are
present they must be identical. New producers should use `access_status`.

The only permitted identity status is `unaccepted-candidate`. Source URLs must
be HTTP(S) locators without URI userinfo, query strings, or fragments. URL path
segments are opaque and cannot be proven token-free, so operators must provide
only non-sensitive public or canonical locators; the grammar reduces but does
not eliminate sensitive-locator risk. Manifests never contain the absolute
authorized-root path, and `source_id` is restricted to a path-free portable
identifier.
