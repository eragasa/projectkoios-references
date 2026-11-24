# `CitationIdentityProjectionStatus`

Closed `StrEnum` for citation-facing identity state:

- `ACCEPTED_ACTIVE_CANONICAL` permits one active canonical citekey from replay.
- `ACCEPTED_WITHOUT_ACTIVE_CITEKEY` is reserved for a future valid replay state
  with accepted identity but no active name; current replay cannot emit it.
- `CANDIDATE_PROPOSED_NONCANONICAL` permits only the candidate's proposed key.
- `INACTIVE_SUPERSEDED` supplies successor reference IDs, not a stale key.
- `UNRESOLVED` reports that the requested opaque ID is absent.

The enum carries identity state only. No value establishes source use,
scientific support, target-bibliography membership, or citation acceptance.

Evidence: [source and tests](../index.md).
