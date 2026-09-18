# Reference evidence contracts

## Status

Proposed under
[`REF-RAG-01`](https://github.com/eragasa/projectkoios-references/issues/1).
This document defines planning boundaries for candidate metadata and later
claim-locator evidence. It does not accept any candidate into the canonical
bibliography or authorize manuscript use.

## Purpose

Project Koios needs reference records that distinguish bibliographic identity,
source access, rights, claim evidence, architecture use, and human acceptance.
These dimensions cannot be collapsed into a single `verified` flag.

This document defines two related but separate records:

1. a candidate reference manifest; and
2. a claim-locator record created only after bibliographic identity is stable.

## Authority boundaries

`projectkoios-references` owns bibliographic identity, candidate state, rights
and access evidence, and reference-object naming. It does not decide:

- whether a scientific claim is correct;
- whether an architecture proposal is accepted;
- whether a source supports a research conclusion;
- whether a candidate belongs in a manuscript; or
- whether a private source may be redistributed.

Those decisions remain with their owning architecture, research, publication,
and human-review processes.

## Candidate reference manifest

A candidate manifest is a deterministic, versioned record for a proposed
reference. It contains at least:

- stable candidate-record identity;
- proposed citekey, explicitly marked noncanonical;
- normalized and source-verbatim titles;
- ordered authors or responsible organizations;
- venue, publisher, edition, volume, issue, and year when applicable;
- persistent identifiers by scheme, including DOI, arXiv, ISBN, or standards
  URI without conflating their identity domains;
- authoritative metadata locators and retrieval dates;
- work/version relationships, such as preprint and published article;
- access status and lawful acquisition status as separate fields;
- rights or redistribution notes with evidence source;
- discrepancy records;
- local-asset availability without publishing private machine paths;
- candidate lifecycle status; and
- manifest contract and generator versions.

An unresolved field remains explicit. Empty text, `unknown`, not-applicable,
and not-yet-verified are distinct states.

## Metadata evidence

Preferred metadata sources are authoritative publisher, proceedings,
standards-body, DOI-registration, repository, institutional, or author records.
A search-result snippet or generated summary is discovery evidence only.

Every normalized value records the source from which it was derived. When two
authoritative sources disagree, the manifest retains both source values and a
typed discrepancy. It does not silently choose the value that best matches an
existing citation.

A DOI, arXiv identifier, ISBN, and URL may refer to related but nonidentical
objects. Version relationships must be represented explicitly rather than
merged by title similarity alone.

## Candidate and canonical identities

A proposed citekey supports planning and navigation only. It is noncanonical
until a human accepts the reference under the repository's canonical process.

For accepted managed reference objects, the identity convention remains:

```text
BibLaTeX key == Markdown basename == PDF basename
```

The convention does not grant acceptance and must not be used to manufacture a
canonical object from unresolved metadata. Renaming or merging accepted objects
requires a separately reviewed migration plan.

## Access and rights

The contract separates:

- metadata publicly visible;
- source content publicly accessible;
- a file lawfully held by the operator;
- permission to process the file locally;
- permission to redistribute the file; and
- permission to quote or publish derived content.

One state never implies another. Acquisition tooling verifies lawfully held
files and known source identities; it does not generalize publisher downloads
or bypass repository controls.

Public manifests and issues omit credentials, signed URLs, cookies,
machine-specific paths, private holdings, and protected source excerpts.
Operational asset locators remain in managed private state.

## Discrepancy records

A discrepancy record contains:

- field or identity domain;
- competing values;
- evidence locators;
- observation date;
- resolution status;
- selected value, if separately accepted; and
- rationale and accepting authority.

Unresolved discrepancies block canonical promotion when they affect work
identity, authorship, title, publication venue, date, edition, or persistent
identifier.

## Claim-locator record

Claim verification is a later task, separate from metadata verification. A
claim-locator record binds:

- stable claim-record identity;
- exact claim text or a stable external claim identity;
- reference candidate or canonical identity;
- source-version identity;
- physical page and printed page label when available;
- section, figure, table, equation, paragraph, or source-span locator;
- exact retained quotation when rights and policy permit it;
- quotation digest and extraction identity;
- relationship type, such as direct statement, contextual evidence,
  methodological precedent, limitation, disagreement, or not found;
- verifier and verification method;
- uncertainty and unresolved interpretation; and
- contract version.

`not found` means that the bounded verification attempt did not locate evidence.
It does not prove that the source is irrelevant or that the claim is false.

Automated retrieval may propose locators. It cannot mark scientific support or
canonical acceptance without the required human review.

## Architecture-use record

When a verified reference motivates an architecture decision, the architecture
record identifies:

- the bounded architecture claim;
- the exact claim-locator record;
- how the evidence informs the decision;
- limitations of applying the source to the Project Koios corpus; and
- alternatives or contradictory evidence considered.

A citation establishes provenance for the rationale. It does not prove that the
chosen architecture is optimal or that corpus-specific evaluation is
unnecessary.

## Determinism and publication

Generated candidate manifests have stable serialization, bounded fields, and
content-derived identity. Identical replay is byte-identical. Existing
incomplete or different immutable output fails closed rather than being
silently repaired.

Publication of a candidate manifest does not publish a private source asset.
Canonical promotion, asset publication, citation acceptance, and manuscript
use each require their own recorded decision.

## Acceptance criteria for REF-RAG-01

The initial RAG design bibliography is ready for later claim verification when:

- every candidate has authoritative metadata evidence or explicit unresolved
  status;
- identifier and work/version relationships are explicit;
- access and redistribution states are distinguished;
- discrepancies are retained and resolved only through recorded evidence;
- generated data serializes and replays deterministically;
- proposed citekeys remain visibly noncanonical; and
- no protected acquisition path or private asset information appears in public
  records.

## Deferred decisions

This contract does not:

- accept the RAG bibliography;
- define scientific relevance judgments;
- authorize source acquisition;
- select manuscript citations;
- decide quotation permissions; or
- define retrieval ranking or generation behavior.
