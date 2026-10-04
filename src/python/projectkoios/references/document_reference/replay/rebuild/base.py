"""Nominal base for independent rebuild replay data objects."""

from abc import ABC

from ...base import (
    AbstractDocumentReferenceDataObject,
)


class AbstractRebuildReplayDataObject(
    AbstractDocumentReferenceDataObject, ABC
):
    """Identify data objects for independent rebuild contracts."""

    __slots__ = ()
