# References codebase technical-debt backlog

## Status and rules

This backlog records weaknesses observed on the merged `master` codebase and
tracks bounded remediation status. It is not a request for a bulk rewrite.

Changes must preserve these boundaries:

- References owns bibliographic identity, provenance, source-asset authority,
  and References-defined projections.
- Ingestion owns document processing and publication.
- Search owns admission and activation.
- Candidate, canonical, asset, review, rights, and publication states remain
  distinct.
- Content identities must not change through an unversioned serializer edit.
- Public or redistribution authority must not be inferred while repairing
  internal structure.
- Hosted continuous integration is an intentional non-goal. Verification must
  remain reproducible through documented local commands.

## Verification and developer workflow

### REF-DEBT-TEST-01 — Hermetic test entry point

**Status:** completed in this remediation.

Make the test suite independent of invocation style, ignored bytecode, stale
empty directories, and prior branch checkout history.

**Observed evidence:**

- `uv run --extra dev pytest -q` cannot import the repository-local `tools`
  modules used by test collection.
- `tests/test__ArchitectureDocumentation.py` checks raw path existence for
  removed packages. Ignored `__pycache__` directories left by a branch switch
  can therefore fail the suite while `git status` remains clean.
- The documented `uv run --extra dev python -m pytest -q` succeeds only after
  those stale ignored directories are removed.

**Acceptance:**

- The documented test command passes from a fresh clone and after switching
  between branches that move or delete packages.
- Direct pytest invocation either works or fails immediately with a documented,
  intentional diagnostic rather than import-collection errors.
- Repository-local test utilities are importable through packaging or explicit
  pytest configuration.
- Architecture assertions inspect tracked/source artifacts and do not treat
  ignored caches or empty directories as implementation modules.
- Tests require no pre-run cache deletion.

## Reference-document catalog contract

### REF-DEBT-DOCREAD-01 — Bound catalog reads before materialization

**Status:** proposed.

Make `ReferenceDocumentReadRequest.max_documents` bound the work performed, not
only the returned tuple.

**Observed evidence:** `ReferenceDocumentReader._control_documents()` reads all
candidates, source assets, observations, and review projection data before the
result-length check. The catalog protocol does not provide bounded candidate or
observation queries, and the source-asset read is called without a limit.

**Acceptance:**

- The reader requests only registry-selected candidate/work identities and the
  evidence required for those records.
- Catalog queries expose explicit limits or exact-key/identity selection and
  fail before partial coverage can be mistaken for success.
- The request limit is enforced before constructing all document results.
- Tests use a catalog larger than the requested slice and prove that unrelated
  records are not loaded or enumerated.
- Missing, ambiguous, and over-limit evidence remain typed failures.

### REF-DEBT-DOCID-01 — Exact and non-retargetable document bindings

**Status:** proposed.

Replace mutable display selectors with explicit immutable identity bindings.

**Observed evidence:** `ReferenceDocumentBinding` stores a proposed citekey and
basename but no candidate ID, canonical work ID, source-asset identity, or
asset-relative path. `ReferenceDocumentReader` joins by proposed citekey. The
registry also rejects duplicate basenames even though distinct assets may
legitimately share names such as `document.pdf` in separate directories.

**Depends on:** an explicit decision whether this contract represents candidate
observations, accepted canonical works, or a separately named non-authoritative
view. It must not silently combine those roles.

**Acceptance:**

- Each binding pins the exact immutable References identity appropriate to its
  declared role.
- A catalog update cannot retarget an unchanged registry identity to another
  candidate or work.
- Selected asset linkage, when present, uses an exact asset/binding identity;
  filename remains display metadata rather than identity authority.
- Distinct assets with the same basename are representable.
- Compatibility with existing registries is explicit: version, migrate, or
  reject; do not reinterpret old bytes.
- Tests cover catalog growth, citekey reuse attempts, duplicate basenames,
  multiple renditions, and missing pinned evidence.

### REF-DEBT-DOCREAD-02 — Preserve the PUBLIC fail-closed boundary

**Status:** completed in this remediation; retain as a regression constraint.

The current public audience returns no documents because publication and rights
authority are not established by this reader. Preserve that behavior until an
owner-approved typed publication contract exists.

**Acceptance:**

- Internal refactoring does not infer public visibility from asset presence,
  review presence, proposed citekeys, or private CONTROL availability.
- Any future PUBLIC result requires explicit rights and publication authority
  owned by the appropriate contract.
- Tests continue to prove that private catalog evidence alone yields no public
  document.

## Content-identity implementation

### REF-DEBT-IDCODEC-01 — Explicit mapping and canonical identity pipeline

**Status:** partial. The reference-document registry now follows the explicit
mapping pipeline; Courses authority identities still require migration and
golden-vector verification.

Replace duplicated stable-ID serialization without introducing generic
Dataclass-to-JSON introspection.

**Observed evidence:** the Courses authority package contains fifteen copies of
`_stable_id` and fifteen copies of `_json_default`; fourteen copies of each are
structurally identical. The remaining variant creates another serialization
surface.

**Acceptance:**

- Each versioned record owns an explicit `to_dict()` mapping and a validating
  `from_dict()` reconstruction boundary.
- `to_json()` serializes only `to_dict()`; `from_json()` parses and delegates
  only to `from_dict()`.
- Domain owners explicitly project enums and nested records. A generic
  `json.dumps(default=...)` Dataclass walker is not used as contract authority.
- A shared internal primitive may canonicalize already JSON-native mappings and
  construct SHA-256 identities, but it does not decide domain fields.
- Every migrated contract retains its current identity and canonical bytes for
  checked-in golden payloads.
- A behavior change requires an explicit contract/version migration rather than
  an in-place helper edit.

## Module and API boundaries

### REF-DEBT-MODULE-01 — Decompose oversized owner implementations

**Status:** proposed.

Reduce change concentration in the largest modules without performing a
repository-wide namespace rewrite.

**Observed hotspots:**

- `state_projection.py`
- `citation/closure.py`
- `identity.py`
- `pdf_corpus.py`
- `assets.py`
- `acquisition.py`
- `courses/authority/queue.py`
- `graph.py`
- `catalog/__init__.py`
- `enrichment.py`
- `review.py`

The root `projectkoios.references` facade also exports a broad set of names,
which increases compatibility and import coupling.

**Acceptance:**

- Decomposition proceeds one cohesive owner capability at a time with unchanged
  public behavior and content identities.
- `ReferenceCatalog` storage, migration, query, and domain-recording concerns
  become independently testable collaborators rather than one expanding class.
- Compatibility facades are deliberately bounded and tested; new code imports
  focused owner modules by default.
- Each slice passes full tests, strict typing, formatting, package build, and
  migration/replay checks before the next slice begins.
- File-size or export-count targets are not used as substitutes for cohesive
  ownership and behavior.

### REF-DEBT-ARCHDOC-01 — Derive architecture coverage without manual mirrors

**Status:** partial. Cache-only directories no longer count as source modules;
the hand-maintained coverage inventories remain.

Retain exact architecture coverage while reducing hand-maintained inventories
that cause merge conflicts and stale documentation gates.

**Observed evidence:** `tests/test__ArchitectureDocumentation.py` manually
mirrors public classes, migrated modules, remaining modules, package trees, and
document paths.

**Acceptance:**

- Public-class and package coverage is derived from source plus a small explicit
  ownership manifest, not duplicated across large Python sets.
- Generated expectations remain reviewable and deterministic.
- Obsolete, missing, orphaned, and broken-link documentation still fails.
- Ignored filesystem artifacts cannot affect coverage.
- The solution introduces no static page or module-count gate.

## Release and compatibility boundary

### REF-DEBT-RELEASE-01 — Define package and Python support policy

**Status:** completed in this remediation.

Clarify when the current internal/pre-release package becomes a versioned
consumer contract.

**Observed evidence:** the package and its pinned base dependency are versioned
`0.0.0`, while the package requires Python 3.14 or newer. Some citation records
are explicitly documented as in-memory prototypes without a durable wire
schema.

**Acceptance:**

- The repository documents whether `0.0.0` means commit-pinned internal use or a
  publishable package surface.
- Before external or irreplaceable consumers depend on a contract, its version,
  compatibility policy, loader behavior, and migration boundary are explicit.
- Supported Python versions are exercised by the documented local verification
  procedure and chosen intentionally.
- Commit pins remain immutable where required, but package versions and contract
  versions are not conflated.
