# `projectkoios.references` package

This package owns reference management and citation handling. It distinguishes
bibliographic observations and candidates, accepted identity replay, source
assets, and deterministic projections without deciding scientific support,
manuscript use, rights clearance, or publication acceptance.

## Documented modules

- [`citations`](citations/index.md) — canonical target citation inventory.
- [`bibliography`](bibliography/index.md) — exact bibliography evidence binding
  and membership state.
- [`citation_identity`](citation_identity/index.md) — a
  bounded citation-facing projection over replay-derived identity state.
- [`citation_document`](citation_document/index.md) — deterministic
  whole-target citation correlation and neutral source-document linkage.

All other package modules remain listed as unmigrated in the
[repository navigator](../../index.md).

## Existing authority surfaces

The documented modules consume the current identity implementation rather
than redefining it:

- [Reference identity and authority](../../../reference-identity.md)
- [Reference evidence contracts](../../../contracts/reference-evidence.md)
- [Citation document control contracts](../../../contracts/citation-document.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- [`projectkoios` namespace](../index.md)
