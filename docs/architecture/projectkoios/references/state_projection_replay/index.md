# `projectkoios.references.state_projection_replay`

This module owns deterministic reduction of a bounded set of typed state claims.
It replaces procedural replay internals with the Project Koios operation flow:

`ReferenceStateReplayRequest → ReferenceStateReplayer → ReferenceStateReplayResult`

## Public classes

- [`ReferenceStateReplayRequest`](ReferenceStateReplayRequest/index.md)
- [`ReferenceStateReplayer`](ReferenceStateReplayer/index.md)
- [`ReferenceStateReplayResult`](ReferenceStateReplayResult/index.md)

## Authority boundary

Replay groups exact observations and decisions without selecting a preferred
source. It cannot promote identity, decide rights, accept scientific support,
authorize manuscript use, accept a contract, or authorize publication.

The legacy `replay_reference_state` function is a compatibility entry point. It
bounds iterable inputs, constructs a typed request, invokes the replayer, and
returns the result projection.

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source: [`state_projection_replay.py`](../../../../../src/python/projectkoios/references/state_projection_replay.py)
- tests: [`test__StateProjection.py`](../../../../../tests/test__StateProjection.py)
- [Package index](../index.md)
