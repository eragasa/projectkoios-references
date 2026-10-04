from __future__ import annotations

import inspect

import pytest
from projectkoios.references.document_reference.base import (
    AbstractDocumentReferenceDataObject,
)
from projectkoios.references.document_reference.replay.same_store.base import (
    AbstractSameStoreReplayDataObject,
)


class _ConcreteSameStoreReplayDataObject(
    AbstractSameStoreReplayDataObject
):
    __slots__ = ()

    def __init__(self) -> None:
        pass


def test__same_store_replay_base__is_distinct_abstract_data_object() -> None:
    assert issubclass(
        AbstractSameStoreReplayDataObject,
        AbstractDocumentReferenceDataObject,
    )
    assert inspect.isabstract(AbstractSameStoreReplayDataObject)
    assert AbstractSameStoreReplayDataObject.__slots__ == ()
    with pytest.raises(TypeError):
        AbstractSameStoreReplayDataObject()


def test__same_store_replay_base__supports_concrete_construction() -> None:
    value = _ConcreteSameStoreReplayDataObject()

    assert isinstance(value, AbstractSameStoreReplayDataObject)
    assert not hasattr(value, "__dict__")
    assert "replay" not in AbstractSameStoreReplayDataObject.__dict__
