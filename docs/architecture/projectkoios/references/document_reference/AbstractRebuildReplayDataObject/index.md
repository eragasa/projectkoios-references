# `AbstractRebuildReplayDataObject`

`AbstractRebuildReplayDataObject` is the nominal owner seam for future
canonical data objects that prove independent rebuild equivalence: applying
once to fresh store A yields A1, applying once to fresh store B yields B1, and
A1 equals B1 logically. It defines no runner, request, result, or replay method.

Evidence: [capability implementation](../implementation.md),
[source](../../../../../../src/python/projectkoios/references/document_reference/replay/rebuild/base.py), and
[tests](../../../../../../tests/package/projectkoios/references/document_reference/replay/rebuild/test__AbstractRebuildReplayDataObject.py).
