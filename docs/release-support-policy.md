# Release and support policy

## Current status

`projectkoios-references` is a commit-pinned internal pre-release package.
Version `0.0.0` does not represent a stable public release, semantic-versioning
promise, or permission to consume undocumented implementation details.

The package currently requires Python 3.14 or newer. Python support is chosen
intentionally at the repository boundary; compatibility with older versions is
not implied.

## Contract boundaries

A Python type, JSON document, catalog schema, or command becomes a supported
consumer contract only when its owner documentation identifies:

- the exact contract and version;
- its authority and non-authority boundaries;
- its canonical serialization and loader behavior;
- compatibility and migration rules;
- the evidence required for authoritative use.

Commit pins and contract versions are separate. A commit pin identifies exact
source code. It does not create a durable wire-format or API compatibility
promise.

Prototype and in-memory records remain replaceable unless their documentation
explicitly declares a durable contract. Existing persisted content identities
must never be reinterpreted by an unversioned serializer change.

## JSON record strategy

Versioned record JSON follows one directional composition:

1. `to_dict()` creates the domain-owned typed mapping.
2. `to_json()` serializes only the result of `to_dict()`.
3. `from_json()` parses JSON and delegates reconstruction to `from_dict()`.
4. `from_dict()` validates the exact field inventory, types, version, and domain
   invariants.

JSON methods must not maintain a second field mapping independent of dictionary
serialization. Domain enums and nested records are projected explicitly by the
owning record rather than through generic dataclass introspection. Any change
that alters accepted mappings or canonical bytes requires an explicit contract
or schema migration.

## Local verification

Hosted continuous integration is intentionally not required. Before merging a
change, run the repository-owned checks from a clean worktree:

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy src/python/projectkoios/references
uv build
```

These commands must not require private reference assets, a live operator
catalog, network discovery, cache deletion, or state from an earlier branch.
When a supported Python version changes, update `requires-python`, Ruff's target,
the documented local environment, and affected contract documentation in the
same reviewed change.

## Future release decision

Before publishing a non-`0.0.0` release or accepting replaceability-sensitive
external consumers, define:

- the supported Python-version range;
- the public import surface;
- package-version compatibility rules;
- versioned persistence and migration policy;
- deprecation and security-fix policy;
- reproducible build and release provenance.

Until then, consumers must use an exact reviewed commit and only the contracts
explicitly documented at that commit.
