"""Reference-collection persistence port."""

from typing import Protocol

from .collection import (
    ReferenceCollection,
)
from .membership import (
    ReferenceCollectionMembership,
)


class ReferenceCollectionRepository(Protocol):
    """Persist collection provenance and membership requirements."""

    def record_collection(self, *, collection: ReferenceCollection) -> None: ...

    def record_membership(
        self,
        *,
        membership: ReferenceCollectionMembership,
    ) -> None: ...
