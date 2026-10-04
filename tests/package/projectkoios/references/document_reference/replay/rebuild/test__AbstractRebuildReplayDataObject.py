from __future__ import annotations

import inspect

import pytest
from projectkoios.references.document_reference.base import (
    AbstractDocumentReferenceDataObject,
)
from projectkoios.references.document_reference.replay.rebuild.base import (
    AbstractRebuildReplayDataObject,
)


class _ConcreteRebuildReplayDataObject(AbstractRebuildReplayDataObject):
    __slots__ = ()

    def __init__(self) -> None:
        pass


def test__rebuild_replay_base__is_distinct_abstract_data_object() -> None:
    assert issubclass(
        AbstractRebuildReplayDataObject,
        AbstractDocumentReferenceDataObject,
    )
    assert inspect.isabstract(AbstractRebuildReplayDataObject)
    assert AbstractRebuildReplayDataObject.__slots__ == ()
    with pytest.raises(TypeError):
        AbstractRebuildReplayDataObject()


def test__rebuild_replay_base__supports_concrete_construction() -> None:
    value = _ConcreteRebuildReplayDataObject()

    assert isinstance(value, AbstractRebuildReplayDataObject)
    assert not hasattr(value, "__dict__")
    assert "replay" not in AbstractRebuildReplayDataObject.__dict__
