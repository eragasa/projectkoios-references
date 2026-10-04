"""Nominal base for same-store replay data objects."""

from abc import ABC

from ...base import (
    AbstractDocumentReferenceDataObject,
)


class AbstractSameStoreReplayDataObject(
    AbstractDocumentReferenceDataObject, ABC
):
    """Identify data objects for same-store idempotence contracts."""

    __slots__ = ()
