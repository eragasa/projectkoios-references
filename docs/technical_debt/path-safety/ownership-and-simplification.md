# Path-safety ownership and simplification

## Status and authority

- Debt state: **identified**.
- Investigation state: **not started**.
- Implementation state: **not started**.
- Sequencing: defer investigation and implementation while the Applications and
  API owner repositories are occupied with current work.

This record is evidence for a later architecture-first investigation. It is not
an ownership decision, migration plan, implementation authorization, or reason
to weaken the current module. Work resumes only when the affected owners are
available and the appropriate coordinator authorizes the next bounded step.

## Current evidence

At References commit `3b8f2604eb701dfae069a08cef1c8610852e1b21`,
[`path_safety.py`](../../../src/python/projectkoios/references/path_safety.py) is
2,115 physical lines. `AuthorizedRoot` begins at line 667 and its class body
runs through line 1,976, immediately before the next module-level function: an
approximately 1,310-line capability object inside one module.

The module is not merely a path-string validator. It currently combines:

- citekey, root-alias, portable segment, and normalized relative-path
  validation;
- root creation, identity binding, and storage-class capability evidence;
- descriptor-relative traversal and child-state inspection;
- symlink, replacement-race, inode, device, and filesystem-boundary
  confinement;
- cloud-placeholder support detection, preflight probing, and observations;
- deterministic file enumeration and incomplete-coverage inventory;
- bounded byte and text reads plus content observations;
- confined directory creation, atomic writes, verified copies, exact removal,
  and an explicitly disabled unsafe rename operation; and
- shared evidence records, typed issue/status values, and path-safety errors.

This responsibility mixture and size justify investigating both simplification
and ownership. They do not establish that References is the wrong owner, that
one replacement owner exists, or that all responsibilities should move
together.

## Current consumer surface

The bounded external production inventory below was captured from the current
owner-repository source trees:

- Applications commit `416be52d539bfbffdbc8a27bd8e13de65404821b`
  imports path-safety capabilities in eleven
  `pdf_corpus_ingestion` modules:
  - root setup and execution: `roots.py`, `cli.py`, and `runner.py`;
  - custody and association: `citation_document_custody.py`,
    `citation_document_registry.py`, and `citation_document_service.py`; and
  - package and review workflows: `document_package.py`,
    `equation_review.py`, `review_queue.py`, `review_tree.py`, and
    `transcript.py`.
- API commit `6963aeb58365887b94a2be282f35e347c2fd2e75`
  imports `AuthorizedRoot` and `RootStorageClass` in
  `equation_review/owner.py` and `transcript_owner.py`.

Applications consumes `AuthorizedRoot`, `RootStorageClass`, placeholder-probe
protocol and implementation types, and placeholder support status. API creates
authorized roots at its owner boundaries. These are active runtime dependencies,
not evidence that either consumer has accepted ownership of the generic
capability.

References itself imports the module from its root facade and from
`acquisition.py`, `assets.py`, `biblatex.py`, `catalog.py`,
`citation_closure.py`, `citation_draft.py`, `citation_identity.py`,
`collection_reconciliation.py`, `coverage.py`, `enrichment.py`, `graph.py`,
`identity.py`, `ingestion_evidence.py`, `models.py`, `naming.py`,
`pdf_corpus.py`, `reconciliation_package.py`, and `validation.py`. Any later
inventory must distinguish generic filesystem mechanics from
References-specific validation and evidence semantics rather than treating the
module as one movable unit.

## Ownership concern

Descriptor-confined filesystem capabilities, cloud-placeholder preflight,
atomic mutation, and generic path validation are broader than reference
management. Keeping them together in References creates a large public
dependency surface for Applications and API and makes reference-specific
changes share a high-risk module with general filesystem protections.

The concern is unresolved. The investigation must first determine which
responsibilities are genuinely generic, which are References evidence policy,
which owner boundaries consume them, and whether keeping, splitting, or moving
any portion improves the architecture. This record deliberately names no
replacement repository or shared framework.

## Non-goals

This debt record does not:

- authorize moving, rewriting, or deleting `path_safety.py`;
- assign the capability to Applications, API, a shared framework, or any other
  owner;
- introduce compatibility facades or speculative abstractions;
- change current public imports, evidence records, or error behavior;
- generalize every References string validator into filesystem policy;
- permit direct `Path` operations to bypass `AuthorizedRoot`; or
- trade protections for fewer lines of code.

## Safety properties that must survive

Any accepted design and migration must preserve, with equivalent or stronger
tests:

1. Paths are normalized, bounded, root-relative, traversal-free, and portable
   where the operation requires portable filesystem names.
2. Root identity is bound to an opened directory, and confined operations use
   descriptor-relative traversal without following symlinks.
3. Root device, leaf inode, regular-file type, and before/after identity checks
   fail closed on replacement races or filesystem-boundary crossings.
4. Cloud-backed storage is explicit. Placeholder state is probed before byte
   access, unsupported or ambiguous preflight cannot claim complete coverage,
   and default mutation of cloud-backed roots remains forbidden.
5. Enumeration, recursion depth, file counts, reads, copies, and observations
   remain bounded. Limit exhaustion remains explicit incomplete evidence, not a
   partial success.
6. Writes remain confined and durable through exclusive temporary files,
   descriptor-relative publication, and directory synchronization. Copies and
   removals retain exact content and race checks; unsafe no-replace rename
   remains disabled unless a proven equivalent exists.
7. Evidence and typed failures remain privacy-reduced and sufficient for
   callers to distinguish absence, access failure, unsafe state, incomplete
   coverage, and filesystem-boundary refusal.

## Bounded investigation

The first authorized investigation must be architecture-first and read-only. It
must:

1. Freeze the source and consumer revisions being evaluated.
2. Inventory public exports and production call sites only within References,
   Applications, and API, plus the tests that prove their safety behavior.
3. Build a responsibility matrix for validation, capability binding, traversal,
   placeholder handling, inventory, reads, mutations, evidence, and errors.
4. Identify which semantics are generic mechanics and which are
   References-owned policy without selecting an owner in advance.
5. Compare keep, split, and move options against dependency direction,
   durability boundaries, migration cost, and every must-preserve property.
6. Return an explicit ownership recommendation and a separately reviewable
   migration sequence before any source changes begin.

The inventory is intentionally bounded to known direct owner repositories and
call sites. Expansion requires evidence of another active consumer; it must not
become an unbounded organization-wide framework search.

## Exit criteria

This debt may be closed only when all of the following are true:

- the responsible architecture authority has recorded an explicit ownership
  decision, including a justified decision to retain ownership if applicable;
- the bounded call-site and safety-test inventory is complete at pinned
  revisions;
- every responsibility has a named owner and a documented API boundary;
- Applications and API owners have reviewed the consumer impact and sequencing;
- executable tests prove every must-preserve property at the final boundary;
- all affected consumers have migrated without a protection gap;
- obsolete exports and implementation are removed only after their real
  durability obligations are satisfied; and
- the resulting References implementation is materially simpler, or an
  approved decision explains why its present scope is necessary.
